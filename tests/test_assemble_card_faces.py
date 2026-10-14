"""Requested immutable half faces reuse ordinary creation, payment and lifetime."""
from copy import deepcopy
from dataclasses import replace
import base64,json
import unittest
from hs_sim.engine import (CardDefinition,CardType,Game,IllegalAction,PlayCard,PlayerSetup,Registry,
    ResolutionError,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.model import EndTurnSpec,Keyword
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.assemble_faces import (AssemblePrefix,AssembleSuffix,AssembleTemplate,
    AssembleRecipe,recipe_from_id)
from hs_sim.engine.effects import (AddToHand,ChoiceOption,CopyMinion,Damage,Destroy,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.registry import UnsupportedDefinitionError
from opening_fixtures import metadata

ALL=('battlecry','deathrattle','end_turn')
TOP=AssembleRecipe('alpha','beta','top').card_id
BOTTOM=AssembleRecipe('alpha','beta','bottom').card_id
END=AssembleRecipe('alpha','gamma','top').card_id

def registry(changed=False,missing=False):
    r=Registry('assembly-printed-halves-diagnostic-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60))
    r.register_behavior('a',lambda c:(GainArmor(c.player_id,2),))
    r.register_behavior('b',lambda c:(GainArmor(c.player_id,5),))
    r.register_behavior('c',lambda c:(GainArmor(c.player_id,3),))
    cards=(CardDefinition('alpha','Primary Alpha',CardType.MINION,cost=2,attack=2,health=3,
               keywords=(Keyword.TAUNT,),deathrattle='a',metadata=metadata(tribes=('beast',))),
        CardDefinition('beta','Secondary Beta',CardType.MINION,cost=4,attack=4,health=4,
               keywords=(Keyword.LIFESTEAL,),battlecry='b',metadata=metadata()),
        CardDefinition('gamma','Secondary Gamma',CardType.MINION,cost=5,attack=5,health=5,
               triggers=(TriggerSpec('turn_ended','c',EndTurnSpec()),),metadata=metadata()))
    for d in cards:r.register_card(d)
    templates=(AssembleTemplate('alpha',AssemblePrefix('deathrattle',(Keyword.TAUNT,)),AssembleSuffix('a',ALL)),
        AssembleTemplate('beta',AssemblePrefix('battlecry',(Keyword.LIFESTEAL,)),AssembleSuffix('b',ALL)),
        AssembleTemplate('gamma',AssemblePrefix('end_turn',end_turn=EndTurnSpec()),AssembleSuffix('c',ALL)))
    for t in templates:
        if missing and t.card_id=='beta':continue
        if changed and t.card_id=='beta':t=replace(t,suffix=replace(t.suffix,allowed_timings=('battlecry','deathrattle')))
        r.register_assemble_template(t)
    def fail(c):raise ResolutionError('Diagnostic pending failure')
    r.register_behavior('fail',fail)
    bodies={'make':lambda c:(AddToHand(c.player_id,TOP,c.source_id),),
        'make.bottom':lambda c:(AddToHand(c.player_id,BOTTOM,c.source_id),),
        'make.end':lambda c:(AddToHand(c.player_id,END,c.source_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'basecopy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id),),
        'revive':lambda c:(ResurrectMinion(c.player_id,c.state.death_history[-1].id,source_id=c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bad':lambda c:(AddToHand(c.player_id,AssembleRecipe('alpha','unknown','top').card_id,c.source_id),),
        'wait':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('make','Make',(AddToHand(c.player_id,TOP,c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior('fail',c.source_id,c.player_id),))),c.source_id),)}
    for name,fn in bodies.items():
        r.register_behavior(name,fn);r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,
            requires_target=name in ('copy','basecopy','bounce','kill','silence')))
    return r

class AssembleCardFaceTests(unittest.TestCase):
    def game(self,hand=('make',),enemy=('bad',)):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,deck=('alpha',)*8,max_mana=10,mana=10),
            PlayerSetup('hero',hand=enemy,deck=('alpha',)*8,max_mana=10,mana=10)),seed=165),registry())
    def card(self,g,name,player=1):return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None):return g.apply(PlayCard(1,self.card(g,name),target))
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return s

    def test_recipe_is_complete_canonical_and_order_sensitive(self):
        r=AssembleRecipe('alpha','beta','top');self.assertEqual(recipe_from_id(r.card_id),r)
        self.assertNotEqual(r.card_id,BOTTOM);self.assertNotEqual(r.card_id,AssembleRecipe('beta','alpha','top').card_id)
        for kw in ({'half':None},{'half':'all'},{'version':'unknown'},{'primary_card_id':TOP}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(r,**kw)

    def test_noncanonical_duplicate_unknown_and_extra_recipe_fields_rejected(self):
        r=registry()
        row={'primary_card_id':'alpha','secondary_card_id':'beta','half':'top','version':'assemble-face-v1'}
        for body in ('{}',json.dumps(row),json.dumps({**row,'extra':1}),'{"half":"top","half":"bottom"}'):
            cid='assemble:'+base64.urlsafe_b64encode(body.encode()).decode().rstrip('=')
            with self.subTest(body=body),self.assertRaises(UnsupportedDefinitionError):r.card(cid)
        for cid in ('assemble:','assemble:@@@@',TOP+'=',AssembleRecipe('alpha','unknown','top').card_id):
            with self.assertRaises(UnsupportedDefinitionError):r.card(cid)

    def test_frozen_lookup_preserves_primary_numbers_name_type_and_metadata(self):
        r=registry();r.freeze();d=r.card(TOP);base=r.card('alpha')
        self.assertEqual((d.cost,d.attack,d.health,d.name,d.kind,d.metadata),
            (base.cost,base.attack,base.health,base.name,base.kind,base.metadata))
        self.assertEqual(d.battlecry,'a');self.assertIsNone(d.deathrattle);self.assertEqual(d.keywords,(Keyword.LIFESTEAL,))
        self.assertEqual(r.card(TOP),d)

    def test_bottom_replacement_keeps_primary_prefix_and_uses_secondary_payload(self):
        d=registry().card(BOTTOM);self.assertEqual(d.deathrattle,'b');self.assertIsNone(d.battlecry)
        self.assertEqual(d.keywords,(Keyword.TAUNT,));self.assertEqual((d.cost,d.attack,d.health),(2,2,3))

    def test_lookup_is_readonly_and_does_not_enumerate_or_change_fingerprint(self):
        r=registry();r.freeze();before=r.fingerprint();keys=tuple(r.cards);count=len(r.cards)
        self.assertIn(TOP,r.cards);self.assertEqual(r.cards[TOP],r.card(TOP));self.assertEqual(r.cards.get(TOP),r.card(TOP))
        self.assertNotIn(TOP,tuple(r.cards));self.assertEqual(tuple(r.cards),keys);self.assertEqual(len(r.cards),count)
        self.assertEqual(r.fingerprint(),before)
        with self.assertRaises(TypeError):r.cards[TOP]=r.card(TOP)
        with self.assertRaises(ValueError):r.register_card(replace(r.card('alpha'),id=TOP))
        with self.assertRaises(ValueError):r.register_assemble_template(r.assemble_templates['alpha'])

    def test_reserved_namespace_cannot_be_registered_as_a_substitute(self):
        r=registry()
        with self.assertRaises(ValueError):r.register_card(replace(r.card('alpha'),id=TOP))

    def test_halves_must_reconstruct_whole_source_before_installation(self):
        r=Registry('invalid');r.register_behavior('a',lambda c:());r.register_card(CardDefinition('a','A',CardType.MINION,health=1,battlecry='a'))
        wrong=AssembleTemplate('a',AssemblePrefix('deathrattle'),AssembleSuffix('a',ALL))
        with self.assertRaises(ValueError):r.register_assemble_template(wrong)
        self.assertFalse(r.assemble_templates)

    def test_unreviewed_text_fields_cannot_silently_survive(self):
        r=Registry('invalid');r.register_behavior('a',lambda c:());r.register_card(CardDefinition('a','A',CardType.MINION,health=1,battlecry='a',spell_damage=1))
        with self.assertRaises(ValueError):r.register_assemble_template(AssembleTemplate('a',AssemblePrefix('battlecry'),AssembleSuffix('a',ALL)))
        self.assertFalse(r.assemble_templates)

    def test_context_compatibility_is_explicit_and_targets_cannot_move_to_deathrattle(self):
        with self.assertRaises(ValueError):AssembleSuffix('b',ALL,requires_target=True)
        r=Registry('contexts');r.register_behavior('a',lambda c:());r.register_behavior('b',lambda c:())
        r.register_card(CardDefinition('a','A',CardType.MINION,health=2,deathrattle='a'))
        r.register_card(CardDefinition('b','B',CardType.MINION,health=2,battlecry='b',targeting=TargetSpec()))
        r.register_assemble_template(AssembleTemplate('a',AssemblePrefix('deathrattle'),AssembleSuffix('a',ALL)))
        r.register_assemble_template(AssembleTemplate('b',AssemblePrefix('battlecry'),AssembleSuffix('b',('battlecry',),targeting=TargetSpec())))
        r.freeze()
        with self.assertRaises(UnsupportedDefinitionError):r.card(AssembleRecipe('a','b','bottom').card_id)
        self.assertIsNone(r.card(AssembleRecipe('a','b','top').card_id).targeting)

    def test_template_missing_body_and_duplicate_declaration_rejected(self):
        r=registry();t=r.assemble_templates['alpha']
        with self.assertRaises(ValueError):r.register_assemble_template(t)
        r=Registry('missing');r.register_card(CardDefinition('a','A',CardType.MINION,health=1,battlecry='missing'))
        with self.assertRaises(UnsupportedDefinitionError):r.register_assemble_template(AssembleTemplate('a',AssemblePrefix('battlecry'),AssembleSuffix('missing',ALL)))
        self.assertFalse(r.assemble_templates)

    def test_definition_and_compatibility_are_bound_to_registry_fingerprint(self):
        self.assertNotEqual(registry().fingerprint(),registry(changed=True).fingerprint())
        self.assertNotEqual(registry().fingerprint(),registry(missing=True).fingerprint())
        g=self.game();self.play(g,'make');s=self.portable(g)
        for r in (registry(changed=True),registry(missing=True)):
            with self.assertRaises(SnapshotError):Game.from_snapshot(s,r)

    def test_creation_payment_and_native_battlecry_use_new_complete_face(self):
        g=self.game();self.play(g,'make');eid=self.card(g,TOP);self.assertEqual(g.quote_cost(eid).amount,2)
        self.play(g,TOP);self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)

    def test_new_face_survives_current_copy_base_copy_and_return_reset(self):
        g=self.game(hand=('make','copy','basecopy','bounce'));self.play(g,'make');self.play(g,TOP);eid=g.state.players[1].board[0]
        self.play(g,'copy',eid);self.play(g,'basecopy',eid);self.play(g,'bounce',eid)
        self.assertEqual(g.state.entities[eid].card_id,TOP);self.assertEqual(g.quote_cost(eid).amount,2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[TOP,TOP])
        self.play(g,TOP);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.portable(g)

    def test_changed_deathrattle_body_uses_original_new_face_material(self):
        g=self.game(hand=('make.bottom','kill'));self.play(g,'make.bottom');self.play(g,BOTTOM);eid=g.state.players[1].board[0]
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.play(g,'kill',eid)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        self.assertEqual(g.state.death_history[-1].card_id,BOTTOM);self.portable(g)

    def test_actual_resurrection_keeps_new_printed_face_and_deathrattle(self):
        g=self.game(hand=('make.bottom','kill','revive','kill'));self.play(g,'make.bottom');self.play(g,BOTTOM)
        original=g.state.players[1].board[0];self.play(g,'kill',original);self.play(g,'revive')
        revived=g.state.players[1].board[0];self.assertNotEqual(revived,original)
        self.assertEqual(g.state.entities[revived].card_id,BOTTOM)
        self.assertEqual((g.state.entities[revived].attack,g.state.entities[revived].health),(2,3))
        self.portable(g);self.play(g,'kill',revived)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,10);self.portable(g)

    def test_printed_battlecry_query_reads_new_face_rather_than_original_primary(self):
        from hs_sim.engine.model import CardAbilityCondition
        from hs_sim.engine.card_conditions import matches_ability
        r=registry();cond=CardAbilityCondition(basis='printed')
        self.assertFalse(matches_ability(cond,r.card('alpha')))
        self.assertTrue(matches_ability(cond,r.card(TOP)))

    def test_silence_preserves_new_printed_numbers_but_removes_new_body(self):
        g=self.game(hand=('make.bottom','silence','kill'));self.play(g,'make.bottom');self.play(g,BOTTOM);eid=g.state.players[1].board[0]
        self.play(g,'silence',eid);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(2,3))
        self.play(g,'kill',eid);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.portable(g)

    def test_native_end_turn_prefix_uses_existing_classified_clock(self):
        from hs_sim.engine import EndTurn
        g=self.game(hand=('make.end',));self.play(g,'make.end');self.play(g,END);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)

    def test_waiting_creation_restores_and_failed_selection_keeps_original_boundary(self):
        g=self.game(hand=('wait',));self.play(g,'wait');s=self.portable(g);choice=g.state.pending_choice.id
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,choice,('fail',)))
        self.assertEqual(g.snapshot(),s);h=Game.from_snapshot(deepcopy(s),registry())
        for game in (g,h):game.apply(SelectChoice(1,choice,('make',)))
        self.assertEqual(g.snapshot(),h.snapshot());self.play(g,TOP);self.portable(g)

    def test_unknown_recipe_creation_rolls_back_without_registry_mutation(self):
        g=self.game(hand=('bad',));s=g.snapshot();fp=g.registry.fingerprint();keys=tuple(g.registry.cards)
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),s);self.assertEqual(g.registry.fingerprint(),fp);self.assertEqual(tuple(g.registry.cards),keys)

    def test_player_commands_use_compiled_definition_without_hidden_enemy_details(self):
        g=self.game();self.play(g,'make');p=g.for_player(1);before=g.snapshot();listing=p.legal_actions()
        action=next(a for a in listing['actions']if a['type']=='play_card')
        self.assertEqual(g.snapshot(),before);self.assertTrue(p.submit({'revision':listing['revision'],'action':action})['accepted'])
        other=g.for_player(2).observe();self.assertNotIn('assemble_templates',json.dumps(other));self.portable(g)

    def test_unknown_definition_and_old_schema_are_rejected_on_restore(self):
        g=self.game();self.play(g,'make');s=self.portable(g);bad=deepcopy(s);eid=str(self.card(g,TOP))
        bad['state']['entities'][eid]['card_id']=AssembleRecipe('alpha','unknown','top').card_id
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        with self.assertRaises(SnapshotError):Game.from_snapshot({**s,'schema_version':251},registry())

if __name__=='__main__':unittest.main()
