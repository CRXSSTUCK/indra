import re
import objectpath
import warnings

from indra.statements import *

residue_names = {
    'S': 'Serine',
    'T': 'Threonine',
    'Y': 'Tyrosine',
    'SER': 'Serine',
    'THR': 'Threonine',
    'TYR': 'Tyrosine',
    'SERINE': 'Serine',
    'THREONINE': 'Threonine',
    'TYROSINE': 'Tyrosine'
    }


class ReachProcessor(object):
    def __init__(self, json_dict, pmid=None):
        self.tree = objectpath.Tree(json_dict)
        self.statements = []
        self.citation = pmid
        if pmid is None:
            if self.tree is not None:
                self.citation =\
                    self.tree.execute("$.events.object_meta.doc_id")
    
    def get_phosphorylation(self):
        qstr = "$.events.frames[(@.type is 'protein-modification') " + \
               "and (@.subtype is 'phosphorylation')]"
        res = self.tree.execute(qstr)
        for r in res:
            epistemics = self._get_epistemics(r)
            if epistemics.get('negative'):
                continue
            frame_id = r['frame_id']
            args = r['arguments']
            site = None
            theme = None
            controller = None

            for a in args:
                if a['argument_label'] == 'theme':
                    theme = a['arg']
                elif a['argument_label'] == 'site':
                    site = a['text']
            qstr = "$.events.frames[(@.type is 'regulation') and " + \
                   "(@.arguments[0].arg is '%s')]" % frame_id
            reg_res = self.tree.execute(qstr)
            controller = None
            for reg in reg_res:
                for a in reg['arguments']:
                    if a['argument_label'] == 'controller':
                        controller = a['arg']

            if controller is None:
                warnings.warn('Skipping phosphorylation with missing controller.')
                continue

            controller_agent = self._get_agent_from_entity(controller)
            theme_agent = self._get_agent_from_entity(theme)
            mod = 'Phosphorylation'
            if site is not None:
                residue, pos = self._parse_site_text(site)
            else:
                residue = ''
                pos = ''
            mod = mod + residue
            sentence = r['verbose-text']
            ev = Evidence(source_api='reach', text=sentence,
                          pmid=self.citation, epistemics=epistemics)
            self.statements.append(Phosphorylation(controller_agent,
                                   theme_agent, mod, pos, ev))
    
    def get_complexes(self):
        qstr = "$.events.frames[@.type is 'complex-assembly']"
        res = self.tree.execute(qstr)
        for r in res:
            epistemics = self._get_epistemics(r)
            if epistemics.get('negative'):
                continue
            frame_id = r['frame_id']
            args = r['arguments']
            sentence = r['verbose-text']
            members = []
            for a in args:
                agent = self._get_agent_from_entity(a['arg'])
                members.append(agent)
            ev = Evidence(source_api='reach', text=sentence, 
                          pmid=self.citation, epistemics=epistemics)
            self.statements.append(Complex(members, ev))
   
    def get_activation(self):
        qstr = "$.events.frames[@.type is 'activation']"
        res = self.tree.execute(qstr)
        for r in res:
            epistemics = self._get_epistemics(r)
            if epistemics.get('negative'):
                continue
            sentence = r['verbose-text']
            context = self._get_context(r)
            ev = Evidence(source_api='reach', text=sentence,
                          pmid=self.citation, annotations=context,
                          epistemics=epistemics)
            frame_id = r['frame_id']
            args = r['arguments']
            for a in args:
                if a['argument_label'] == 'controller':
                    controller = a.get('arg')
                    # When the controller is not a simple entity
                    if controller is None:
                        if a['argument-type'] == 'complex':
                            controllers = a.get('args').values()
                            controller_agent =\
                                self._get_agent_from_entity(controllers[0])
                            bound_contr = [self._get_agent_from_entity(c) 
                                           for c in controllers[1:]]
                            controller_agent.bound_to = bound_contr
                    else:
                        controller_agent =\
                            self._get_agent_from_entity(controlled)
                if a['argument_label'] == 'controlled':
                    controlled = a['arg']
            controlled_agent = self._get_agent_from_entity(controlled)
            if r['subtype'] == 'positive-activation':
                rel = 'increases'
            else:
                rel = 'decreases'
            st = ActivityActivity(controller_agent, 'Activity', rel,
                                  controlled_agent, 'Activity', ev)
            self.statements.append(st)
   
    def _get_context(self, frame_term):
        try:
            context_term = frame_term['context']
        except KeyError:
            return {}

        species = context_term.get('Species')
        cell_type = context_term.get('CellType')
        context = {}
        context['species'] = species
        context['cell_type'] = cell_type
        return context

    def _get_agent_from_entity(self, entity_id):
        qstr = "$.entities.frames[(@.frame_id is \'%s\')]" % entity_id
        res = self.tree.execute(qstr)
        if res is None:
            return None
        entity_term = res.next()
        name = self._get_agent_name(entity_term['text'])
        db_refs = {}
        for xr in entity_term['xrefs']:
            if xr['namespace'] == 'uniprot':
                db_refs['UP'] = xr['id']
        agent = Agent(name, db_refs=db_refs)
        return agent
  
    @staticmethod
    def _get_epistemics(event):
        epistemics = {}
        # Check whether information is negative
        neg = event.get('is_negated')
        if neg is True:
            epistemics['negative'] = True
        hyp = event.get('is_hypothesis')
        if hyp is True:
            epistemics['hypothesis'] = True
        return epistemics

    @staticmethod
    def _get_agent_name(txt):
        '''
        Produce valid agent name from string.
        '''
        name = txt.replace('-', '_')
        name = name.replace(' ', '_')
        name = name.replace('.', '_')
        return name

    @staticmethod
    def _parse_site_text(s):
        m = re.match(r'([TYS])[-]?([0-9]+)', s)
        if m is not None:
            residue = residue_names[m.groups()[0]]
            site = m.groups()[1]
            return residue, site

        m = re.match(r'(THR|TYR|SER)[- ]?([0-9]+)', s.upper())    
        if m is not None:
            residue = residue_names[m.groups()[0]]
            site = m.groups()[1]
            return residue, site

        m = re.match(r'(THREONINE|TYROSINE|SERINE)[^0-9]*([0-9]+)', s.upper())
        if m is not None:
            residue = residue_names[m.groups()[0]]
            site = m.groups()[1]
            return residue, site

        m = re.match(r'.*(THREONINE|TYROSINE|SERINE).*', s.upper())
        if m is not None:
            residue = residue_names[m.groups()[0]]
            site = None
            return residue, site
       
        return '', None
