"""Whole native slots, ordinary producers, fixed families and real weapon slots."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_summon_companion_equipment_fragments import SOURCES,DEPENDENCIES,PROFILES,PREFIX,load_batch,register_assemble_summon_companion_equipment_fragments
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import FLESH,POOL_ID as ASSEMBLY_POOL
from hs_sim.cards.entry_native_cards import FEL_BEASTS
from hs_sim.cards.simple_followup_p13_cards import COMPANIONS
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,Keyword,LimitedTriggerSpec,Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture,META,DECK,COIN,UNIT,KILL,COPY,MUTE,BOUNCE

MONGREL,SNEED,MAZE,ATLAS,DOG,PAST,MAW,SPEAKER,TIRION=SOURCES
FLY,RUST,CURATOR,DRAGON,LOOT,DOOM,HEAL,CAIRNE,KHADGAR='CORE_UNG_809','CORE_SW_072','CORE_KAR_061','CORE_UNG_848','CORE_EX1_096','CORE_NEW1_021','EDR_971','CORE_EX1_110','CORE_DAL_575'
P='fixture.assemble_pool_summon.'
G1,G2,G4,G5,GL,GP,MARK,ARMOR,WATCH,FAULT,UNKNOWN=(P+x for x in
    ('one_death','two','four','five_taunt','legend','past','battlecry_marker','armor','watch','fault','unknown'))
GEN=(G1,G2,G4,G5,GL,GP)
CTX=GenerationContext('k407-reviewed-summon-source-fixture','experimental')


def primary(source):return DRAGON if source in (ATLAS,PAST,TIRION)else CURATOR if source in(MONGREL,SNEED,MAW)else FLY if source==DOG or source==MAZE else RUST
def card(source):return AssembleRecipe(primary(source),source,'bottom').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k407.'+mode
    r.register_behavior(MARK,lambda c:(GainArmor(c.player_id,7),));r.register_behavior(ARMOR,lambda c:(GainArmor(c.player_id,2),))
    for cid,cost,rarity in ((G1,1,Rarity.COMMON),(G2,2,Rarity.COMMON),(G4,4,Rarity.COMMON),
            (G5,5,Rarity.COMMON),(GL,6,Rarity.LEGENDARY),(GP,3,Rarity.COMMON)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,
            battlecry=MARK if cid!=G1 else None,deathrattle=ARMOR if cid==G1 else None,
            keywords=(Keyword.TAUNT,)if cid==G5 else(),
            metadata=CardMetadata(True,(CardClass.NEUTRAL,),rarity,tribes=(),factions=(),subtypes=()))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    if mode=='unknown':r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,4,
        CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())))
    if mode!='no_general':r.register_pool(PoolDefinition('constructed.cards','diagnostic-summon-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(x)for x in ((UNKNOWN,)if mode=='unknown'else GEN[:-1])),complete=True))
    if mode!='no_past':r.register_pool(PoolDefinition('constructed.past.cards','diagnostic-past-domain-v1',CTX.target_id,CTX.mode,
        (PoolMember(GP),),complete=True))
    members=(LOOT,SPEAKER,RUST)if mode=='flesh'else(RUST,MONGREL,CAIRNE)
    if mode=='missing':r._assemble_templates.pop(MONGREL)
    if mode!='no_assembly':r.register_pool(PoolDefinition(ASSEMBLY_POOL,'three-real-summon-sources-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(x)for x in members),complete=True))
    def fault(c):raise ResolutionError('deliberate assembled summon arrival fault')
    r.register_behavior(FAULT,fault)
    r.register_trigger_condition(WATCH,lambda c:c.event.player_id==c.player_id and
        c.state.entities[c.event.target_id].card_id in GEN+FEL_BEASTS+COMPANIONS)
    r.register_behavior(WATCH,lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
        ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        limited_triggers=(LimitedTriggerSpec('minion_summoned',WATCH,condition_id=WATCH),)))
    return r


class AssembleSummonCompanionEquipmentTests(unittest.TestCase):
    def game(self,hand=(),board=(),mode='normal',hero='HERO_08'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),seed=407,generation_context=CTX),fixture(mode))
    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target_id=target));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def choose_face(self,g,cid):self.choose(g,next(x.id for x in g.state.pending_choice.options if x.card_id==cid))
    def outputs(self,g):return [g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id in GEN+FEL_BEASTS+COMPANIONS]
    def roots(self,g,eid):return [x for x in g.state.card_summon_history if x.request.cause.source.entity_id==eid]
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def weapon(self,g):return g.state.entities[g.state.players[1].weapon_id]
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_sixteen_complete_records_thirty_two_primary_faces_and_whole_fixed_dependencies(self):
        data=load_batch();rows={x['record']['id']:x for x in data['existing_dependencies']};r=build_registry()
        self.assertEqual(tuple(rows),SOURCES+DEPENDENCIES);self.assertEqual(len(data['official_observations']),32)
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale']);path=Path(obs['response_file'])
            self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])

    def test_all_nine_whole_faces_and_five_exact_native_death_bodies_reconstruct(self):
        r=build_registry();fp=r.fingerprint()
        for source in SOURCES:
            d=r.card(source);t=r.assemble_templates[source];face=r.card(AssembleRecipe(source,source,'top').card_id)
            self.assertEqual(asdict(face),asdict(d)|{'id':face.id})
            if source in PROFILES:
                self.assertEqual(t.suffix.deathrattle_behavior_id,d.deathrattle);self.assertTrue(t.suffix.behavior_id.startswith(PREFIX))
            else:self.assertEqual(t.suffix.behavior_id,d.battlecry or d.deathrattle)
        self.assertEqual(r.fingerprint(),fp)
        with self.assertRaises(UnsupportedDefinitionError):r.pool(ASSEMBLY_POOL,CTX)

    def test_each_paid_battlecry_uses_original_pool_filter_count_or_complete_fixed_child(self):
        expected={MONGREL:[G4,G4],SNEED:[GL],MAZE:[G2],ATLAS:[G5],DOG:[G1],PAST:[GP]}
        for source in SOURCES:
            with self.subTest(source=source):
                cid=card(source);g=self.game(hand=(cid,));before=g.state.players[1].mana;eid=self.play(g,cid)
                if source==SPEAKER:self.choose(g,COMPANIONS[0])
                out=self.outputs(g);self.assertEqual(g.state.players[1].mana,before-g.registry.card(primary(source)).cost)
                if source in expected:self.assertEqual([x.card_id for x in out],expected[source])
                elif source==MAW:
                    self.assertEqual(len(out),1);self.assertIn(out[0].card_id,FEL_BEASTS)
                    d=g.registry.card(out[0].card_id);self.assertEqual((out[0].attack,out[0].health),(d.attack,d.health));self.assertEqual(out[0].keywords,frozenset(d.keywords))
                elif source==SPEAKER:self.assertEqual([x.card_id for x in out],[COMPANIONS[0]])
                else:
                    weapon=self.weapon(g);self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),('EX1_383t',5,3))
                self.assertEqual(self.armor(g),0);self.assertTrue(g.state.battlecry_history[-1].completed)
                self.assertTrue(all(x.request.cause.source.card_id==cid for x in self.roots(g,eid)))

    def test_real_mismatch_two_pool_roots_with_khadgar_make_four_without_child_battlecries(self):
        cid=AssembleRecipe(RUST,MONGREL,'bottom').card_id
        cls=fixture().card(MONGREL).metadata.classes[0]
        hero={CardClass.WARLOCK:'HERO_07',CardClass.HUNTER:'HERO_05',CardClass.SHAMAN:'HERO_02'}.get(cls,'HERO_08')
        g=self.game(hand=(MISMATCH,),board=(KHADGAR,),hero=hero);self.play(g,MISMATCH);self.choose_face(g,cid);eid=self.play(g,cid)
        self.assertEqual(len(self.outputs(g)),4);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(len(self.roots(g,eid)),2);self.assertEqual(self.armor(g),0)

    def test_real_flesh_dead_companion_choice_waits_restores_and_arrival_failure_rolls_back(self):
        cid=AssembleRecipe(LOOT,SPEAKER,'bottom').card_id
        g=self.game(hand=(FLESH,KILL),board=(WATCH,),mode='flesh',hero='HERO_05');self.play(g,FLESH);self.choose_face(g,cid)
        eid=self.play(g,cid);self.play(g,KILL,eid);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(tuple(x.card_id for x in g.state.pending_choice.options),COMPANIONS);self.portable(g)
        self.choose(g,COMPANIONS[2]);saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'assembled summon arrival fault'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.assertEqual([x.card_id for x in self.outputs(g)],[COMPANIONS[2]])
        self.assertTrue(g.state.deathrattle_history[-1].completed);self.assertFalse(g.state.draw_history)
        public=json.dumps(g.observe(2),ensure_ascii=False)
        for private in ('card_summon_history','pool_summon_history','source_guard','resolution_frame'):self.assertNotIn(private,public)

    def test_native_death_slot_stays_bound_to_actual_new_carrier(self):
        cid=AssembleRecipe(LOOT,DOG,'bottom').card_id
        g=self.game(hand=(KILL,),board=(UNIT,cid,UNIT));left,eid,right=g.state.players[1].board;self.play(g,KILL,eid)
        board=g.state.players[1].board;self.assertEqual((board[0],board[2]),(left,right));self.assertEqual(g.state.entities[board[1]].card_id,G1)
        self.assertEqual(self.roots(g,eid)[0].request.cause.source.card_id,cid);self.assertTrue(g.state.deathrattle_history[-1].completed)

    def test_non_death_owner_end_and_start_do_not_fabricate_death_context(self):
        for base,source in ((HEAL,DOG),(DOOM,MAZE)):
            with self.subTest(base=base):
                cid=AssembleRecipe(base,source,'bottom').card_id;g=self.game(hand=(cid,));self.play(g,cid);self.assertFalse(self.outputs(g))
                g.apply(EndTurn(1))
                if base==DOOM:self.assertFalse(self.outputs(g));g.apply(EndTurn(2))
                self.assertEqual([x.card_id for x in self.outputs(g)],[G1 if source==DOG else G2]);self.assertFalse(g.state.deathrattle_history)

    def test_past_pool_stays_independent_and_missing_past_never_falls_back_to_standard(self):
        cid=card(PAST);g=self.game(hand=(cid,),mode='no_general');self.play(g,cid);self.assertEqual([x.card_id for x in self.outputs(g)],[GP])
        g=self.game(hand=(cid,),mode='no_past');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)

    def test_fixed_fel_family_full_board_keeps_materials_but_skips_random_selection(self):
        cid=card(MAW);g=self.game(hand=(cid,),board=(UNIT,)*6);rng=g.snapshot()['rng_state'];self.play(g,cid)
        self.assertFalse(self.outputs(g));self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_weapon_body_replaces_actual_slot_and_also_equips_after_natural_death(self):
        cid=card(TIRION);g=self.game(hand=('CS2_106',cid));old=self.play(g,'CS2_106');eid=self.play(g,cid)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(self.weapon(g).card_id,'EX1_383t')
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords)
        death=AssembleRecipe(CAIRNE,TIRION,'bottom').card_id;g=self.game(hand=(KILL,),board=(death,));eid=g.state.players[1].board[0]
        self.play(g,KILL,eid);self.assertFalse(g.state.players[1].board);self.assertEqual(self.weapon(g).durability,3)
        self.assertTrue(g.state.deathrattle_history[-1].completed)

    def test_current_copy_silence_and_return_preserve_new_end_summon_face(self):
        cid=AssembleRecipe(HEAL,DOG,'bottom').card_id
        g=self.game(hand=(COPY,MUTE,BOUNCE),board=(cid,));eid=g.state.players[1].board[0];self.play(g,COPY,eid);self.play(g,MUTE,eid)
        g.apply(EndTurn(1));self.assertEqual(len(self.outputs(g)),1);g.apply(EndTurn(2));self.play(g,BOUNCE,eid);self.play(g,cid)
        g.apply(EndTurn(1));self.assertEqual(len(self.outputs(g)),3)

    def test_two_selected_entries_remain_frozen_when_only_one_board_space_survives(self):
        cid=card(MONGREL);empty=self.game(hand=(cid,));self.play(empty,cid)
        full=self.game(hand=(cid,),board=(UNIT,)*5);eid=self.play(full,cid)
        self.assertEqual(len(self.outputs(full)),1);self.assertEqual(full.snapshot()['rng_state'],empty.snapshot()['rng_state'])
        self.assertEqual(full.state.pool_summon_history[-1].selected,(G4,G4))
        self.assertEqual([d.outcome for r in self.roots(full,eid)for d in r.deliveries],['delivered','board_full'])

    def test_eligible_unknown_fails_before_rng_even_full_and_missing_generation_domain_rolls_back(self):
        cid=card(MONGREL)
        for mode,board in (('unknown',()),('unknown',(UNIT,)*6),('no_general',())):
            g=self.game(hand=(cid,),board=board,mode=mode);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved)

    def test_missing_assembly_or_fragment_and_whole_child_pin_reject_without_partial_installation(self):
        for mode in ('no_assembly','missing'):
            g=self.game(hand=(MISMATCH,),mode=mode,hero='HERO_02');saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,MISMATCH)
            self.assertEqual(g.snapshot(),saved)
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        for cid in PROFILES:r._behaviors.pop(PREFIX+cid)
        r._cards['EX1_383t']=replace(r.card('EX1_383t'),attack=6)
        with self.assertRaisesRegex(TargetValidationError,'complete original source or fixed dependency'):register_assemble_summon_companion_equipment_fragments(r)
        self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES));self.assertTrue(all(PREFIX+cid not in r._behaviors for cid in PROFILES))


if __name__=='__main__':unittest.main()
