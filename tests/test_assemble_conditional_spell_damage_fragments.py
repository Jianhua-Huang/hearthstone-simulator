"""Actual authored condition stays on the prefix; copies keep native life rules."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_conditional_spell_damage_fragments import CARD,CONDITION,BODY,load_batch
from hs_sim.cards.native_assemble_entry_cards import FETCHER,POOL_ID
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,
    SelectChoice,TriggerSpec)
from hs_sim.engine.assemble_faces import (AssembleRecipe,AssemblePrefix,AssembleSuffix,AssembleTemplate,
    CONDITION_PREFIX,condition_behavior_id,printed_face,compatible)
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import ChoiceOption,Damage,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError,RuleContext
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import (fixture as base_fixture,META,DECK,BEAST,DRAGON,
    MURLOC,HAWK,COIN,S1,S2,S3)

DRAIN,CURATOR,CAIRNE,TARGET='CORE_GIL_622','CORE_KAR_061','CORE_EX1_110','CORE_UNG_084'
P='fixture.conditional_spell_damage.'
HIT,ZERO,ABILITY,ENEMY,ARMOR,OBS,FAULT=(P+x for x in('hit','zero','ability','enemy','armor','observer','fault'))
CTX=GenerationContext('k397-reviewed-conditional-fixture','experimental')
DRAW=AssembleRecipe(CARD,CURATOR,'bottom').card_id
COPY=AssembleRecipe(CARD,DRAIN,'top').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__();r._version+='.k397.'+mode
    bodies={HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        ZERO:lambda c:(Damage(c.state.players[2].hero_id,0,c.source_id,DamageKind.SPELL),),
        ABILITY:lambda c:(Damage(c.state.players[2].hero_id,1,c.source_id,DamageKind.MINION_ABILITY),),
        ENEMY:lambda c:(CastSpell(2,HIT,c.source_id),),ARMOR:lambda c:(GainArmor(2,5),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        if cid==ABILITY:
            r.register_card(CardDefinition(cid,cid,CardType.MINION,health=1,battlecry=cid,metadata=META))
        else:
            r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
                targeting=TargetSpec(kinds=(CardType.HERO,),relation='enemy')if cid==HIT else None))
    def fault(c):raise ResolutionError('deliberate conditional assembly observer fault')
    r.register_behavior(FAULT,fault)
    def observe(c):
        target=c.state.entities[c.event.target_id]
        if not target.card_id.startswith('assemble:'):return ()
        if sum(c.state.entities[i].card_id==target.card_id for i in c.state.players[c.player_id].board)!=1:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('skip','Continue'),
            ChoiceOption('hit','Enable condition',(CastSpell(c.player_id,HIT,c.source_id),)),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(OBS,observe)
    r.register_card(CardDefinition(OBS,OBS,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('minion_summoned',OBS),)))
    secondary=CAIRNE if mode=='pending_death'else TARGET if mode=='pending_arrow'else CURATOR
    if mode=='missing':r._assemble_templates.pop(CARD)
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL_ID,'three-real-conditional-fixture-v1',CTX.target_id,
        CTX.mode,(PoolMember(CARD,1000),PoolMember(DRAIN),PoolMember(secondary)),complete=True))
    return r


class AssembleConditionalSpellDamageTests(unittest.TestCase):
    def game(self,hand=(),board=(),deck=DECK,mode='normal'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),
            seed=397,generation_context=CTX),fixture(mode))

    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid

    def hit(self,g):self.play(g,HIT,g.state.players[2].hero_id)
    def drawn(self,g):return [r for r in g.state.draw_history if r.player_id==1]
    def count(self,g,cid):return sum(g.state.entities[i].card_id==cid for i in g.state.players[1].board)

    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def test_complete_original_two_primary_faces_and_explicit_native_bridge(self):
        data=load_batch();row=data['existing_dependencies'][0];r=build_registry();d=r.card(CARD)
        self.assertEqual(canonical_digest(asdict(d)),row['definition_sha256'])
        self.assertEqual(len(data['official_observations']),2)
        for obs in data['official_observations']:
            check_face(row['record'],obs['face'],obs['locale']);path=Path(obs['response_file'])
            self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        t=r.assemble_templates[CARD];face=printed_face(d,t.prefix,t.suffix,CARD)
        self.assertEqual(t.original_battlecry_id,d.battlecry)
        self.assertEqual(replace(face,battlecry=t.original_battlecry_id),d)
        self.assertTrue(face.battlecry.startswith(CONDITION_PREFIX))
        self.assertEqual(t.suffix.pending_timings,('deathrattle',))
        self.assertEqual(recipe_options(r,CARD,CARD),())
        with self.assertRaises(UnsupportedDefinitionError):r.pool(POOL_ID,CTX)

    def test_real_fetcher_keeps_complete_offer_and_delivers_conditional_draw_face(self):
        g=self.game(hand=(FETCHER,HIT));self.play(g,FETCHER)
        q=g.state.pending_choice;option=next(x for x in q.options if x.card_id==DRAW)
        self.portable(g);g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
        self.hit(g);before=g.state.players[1].mana;source=self.play(g,DRAW)
        self.assertEqual(g.state.players[1].mana,before-4)
        self.assertEqual(g.state.entities[source].base_attack,2)
        self.assertEqual([x.card_id for x in self.drawn(g)],[BEAST,DRAGON,MURLOC])
        self.assertEqual(self.count(g,DRAW),1)

    def test_false_condition_suppresses_new_payload_but_keeps_printed_spell_damage(self):
        g=self.game(hand=(DRAW,'CS2_029'));self.play(g,DRAW)
        self.assertFalse(self.drawn(g));self.assertTrue(g.state.battlecry_history[-1].completed)
        self.play(g,'CS2_029',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,23)

    def test_only_positive_own_spell_damage_in_the_current_global_turn_enables_the_prefix(self):
        for before,expected in ((HIT,3),(ZERO,0),(ABILITY,0),(ENEMY,0)):
            with self.subTest(before=before):
                g=self.game(hand=(before,DRAW))
                if before==HIT:self.hit(g)
                else:self.play(g,before)
                self.play(g,DRAW);self.assertEqual(len(self.drawn(g)),expected)
        g=self.game(hand=(HIT,DRAW));self.hit(g);g.apply(EndTurn(1));g.apply(EndTurn(2))
        before=len(self.drawn(g));self.play(g,DRAW);self.assertEqual(len(self.drawn(g)),before)

    def test_real_spell_damage_to_armor_also_qualifies_the_history_condition(self):
        g=self.game(hand=(ARMOR,HIT,DRAW));self.play(g,ARMOR);self.hit(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.play(g,DRAW);self.assertEqual(len(self.drawn(g)),3)

    def test_replacing_the_prefix_removes_spell_damage_and_original_condition_from_self_copy(self):
        g=self.game(hand=(COPY,'CS2_029'));source=self.play(g,COPY)
        self.assertEqual(self.count(g,COPY),2)
        self.assertEqual(len([b for b in g.state.battlecry_history if b.card_id==COPY]),1)
        self.assertEqual(g.registry.card(COPY).spell_damage,0)
        self.play(g,'CS2_029',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)
        self.assertTrue(all(g.state.entities[i].max_health==5 for i in g.state.players[1].board if g.state.entities[i].card_id==COPY))
        self.assertEqual(g.state.entities[source].base_cost,4)

    def test_borrowed_self_copy_uses_the_new_primary_body_without_importing_the_original_condition(self):
        cid=AssembleRecipe(HAWK,CARD,'bottom').card_id
        g=self.game(hand=(cid,));source=self.play(g,cid)
        bodies=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertEqual(len(bodies),2)
        self.assertTrue(all((x.card_id,x.attack,x.max_health)==(cid,3,1)for x in bodies))
        self.assertEqual(g.registry.card(cid).spell_damage,0)
        self.assertEqual(len(g.state.battlecry_history),1)

    def test_original_native_card_keeps_its_existing_condition_and_damage_bonus_on_both_copies(self):
        g=self.game(hand=(HIT,CARD,'CS2_029'));self.hit(g);self.play(g,CARD)
        self.assertEqual(self.count(g,CARD),2)
        self.play(g,'CS2_029',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,21)

    def test_body_acceptance_reads_committed_arrival_reaction_and_waiting_resume_is_atomic(self):
        g=self.game(hand=(DRAW,),board=(OBS,));self.play(g,DRAW)
        self.assertFalse(self.drawn(g));saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'conditional assembly observer fault'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'hit')
        self.assertEqual(len(self.drawn(g)),3);self.portable(g)
        for pid in(1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for name in('original_battlecry_id','pending_timings','source_guard'):
                self.assertNotIn('"'+name+'"',public)

    def test_owner_start_self_copy_uses_the_original_frozen_listener_and_does_not_copy_the_condition(self):
        cid=AssembleRecipe(CARD,'BE_873','top').card_id
        g=self.game(hand=(cid,));self.play(g,cid);self.assertEqual(self.count(g,cid),1)
        g.apply(EndTurn(1));self.assertEqual(self.count(g,cid),1)
        g.apply(EndTurn(2));self.assertEqual(self.count(g,cid),2)
        self.assertEqual(g.registry.card(cid).spell_damage,0)

    def test_unverified_death_and_conditional_arrow_pairs_are_errors_not_silently_removed_candidates(self):
        r=build_registry()
        for cid in(AssembleRecipe('CORE_LOOT_413',CARD,'bottom').card_id,
                AssembleRecipe(CARD,TARGET,'bottom').card_id):
            with self.subTest(cid=cid),self.assertRaisesRegex(UnsupportedDefinitionError,'Eligible'):
                r.card(cid)
        for mode in('pending_death','pending_arrow','missing','no_pool'):
            with self.subTest(mode=mode):
                g=self.game(hand=(FETCHER,),mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,FETCHER)
                self.assertEqual(g.snapshot(),before)

    def test_canonical_derived_identity_reserved_namespace_and_native_context_are_enforced(self):
        r=build_registry();bid=condition_behavior_id(CONDITION,BODY)
        with self.assertRaises(ValueError):r.register_behavior(bid,lambda c:())
        for bad in(CONDITION_PREFIX,CONDITION_PREFIX+'@@@@',bid+'=',
                condition_behavior_id('fixture.unknown.condition',BODY),condition_behavior_id(CONDITION,'fixture.unknown.body')):
            with self.subTest(bad=bad),self.assertRaises(UnsupportedDefinitionError):r.behavior(bad)
        with self.assertRaises(ValueError):AssembleSuffix(bid,('battlecry',))
        with self.assertRaises(ValueError):AssemblePrefix('deathrattle',condition_id=CONDITION)
        with self.assertRaises(ValueError):AssemblePrefix('battlecry',spell_damage=True)
        with self.assertRaises(ValueError):AssembleSuffix(BODY,('battlecry',),pending_timings=('battlecry',))
        g=self.game();context=RuleContext(g.state,g.state.players[1].hero_id,1)
        with self.assertRaisesRegex(ValueError,'native Battlecry'):r.behavior(bid)(context)

    def test_exact_original_bridge_is_required_and_cannot_mask_other_source_fields(self):
        r=build_registry();template=r._assemble_templates.pop(CARD)
        for bad in(replace(template,original_battlecry_id=None),
                replace(template,original_battlecry_id='cards.simple_followup_p48.EDR_940'),
                replace(template,prefix=replace(template.prefix,spell_damage=0))):
            with self.subTest(bad=bad),self.assertRaises(ValueError):r.register_assemble_template(bad)
        self.assertNotIn(CARD,r.assemble_templates)


if __name__=='__main__':unittest.main()
