"""Real constructed requests and immutable assembled family-skill sources."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_discovery_copy_count_fragments import (
    SOURCES,SKILLS,FANATIC,FAMILY,load_batch,register_assemble_discovery_copy_count_fragments)
from hs_sim.cards.native_assemble_entry_cards import NURTURER,POOL_ID as ASSEMBLY_POOL
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,Zone)
from hs_sim.engine.ability_families import assembled_trigger_source
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.battlecry_sources import RepeatBattlecry
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChangeControl,Damage,GainArmor,ModifyCost)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,CostSpec,DamageKind,Rarity,SpellSchool,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture,META,COIN,KILL,MUTE

CARRIER,RUMBLER,OOZE,ASTRO,TORMENTOR,ENDMAW,GIFT_COPY,LOWEST,ARCHITECT,STALKER,FILL,SCAVENGER=SOURCES
FLY,LOOT,END,START='CORE_UNG_809','CORE_EX1_096','EDR_971','CORE_NEW1_021'
P='fixture.assemble_discovery_copy_count.'
ONE,BEAST3,LEGEND3,MINION5,BIG=(P+x for x in('one','beast3','legend3','minion5','big'))
SPELLS=tuple(P+'spell5_'+str(i)for i in range(3));FOREIGN=P+'foreign5'
DISCOUNT,GIVE,HISTORY,UNKNOWN=(P+x for x in('discount','give','history','unknown'))
POOL='constructed.cards';CTX=GenerationContext('k413-reviewed-discovery-copy-count','experimental')
DEFAULT_FP='b2167d3328df10bb4336983812adfd12220d2644b7bcc86b517f5e335028eb4a'


def face(prefix,suffix):return AssembleRecipe(prefix,suffix,'bottom').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k413.'+mode
    def metadata(cls=CardClass.NEUTRAL,tribes=(),legend=False):
        return CardMetadata(True,(cls,),Rarity.LEGENDARY if legend else Rarity.COMMON,tribes=tribes)
    r.register_behavior(P+'one',lambda c:(GainArmor(c.player_id,7),))
    for cid,cost,tribes,legend in ((ONE,1,('beast',),False),(BEAST3,3,('beast',),False),
            (LEGEND3,3,('demon',),True),(MINION5,5,(),False)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=4,metadata=metadata(tribes=tribes,legend=legend),
            battlecry=P+'one'if cid==ONE else None)
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_card(CardDefinition(BIG,BIG,CardType.MINION,health=40,metadata=META))
    r.register_behavior(P+'hit',lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),))
    for cid in (*SPELLS,FOREIGN):
        d=CardDefinition(cid,cid,CardType.SPELL,cost=5,spell_school=SpellSchool.FIRE,on_play=P+'hit',
            metadata=metadata(CardClass.WARLOCK if cid==FOREIGN else CardClass.MAGE))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_behavior(DISCOUNT,lambda c:(ModifyCost(c.target_id,CostSpec(set_to=0),c.source_id),))
    r.register_card(CardDefinition(DISCOUNT,DISCOUNT,CardType.SPELL,on_play=DISCOUNT,metadata=META,
        targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')))
    r.register_behavior(GIVE,lambda c:(ChangeControl(c.target_id,2),))
    r.register_card(CardDefinition(GIVE,GIVE,CardType.SPELL,on_play=GIVE,metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    def history(c):
        original=next(row for row in c.state.battlecry_history if row.card_id==face(FLY,RUMBLER)and row.completed)
        return(RepeatBattlecry(c.player_id,c.source_id,original.id,choices='player'),)
    r.register_behavior(HISTORY,history)
    r.register_card(CardDefinition(HISTORY,HISTORY,CardType.MINION,health=8,battlecry=HISTORY,metadata=META))
    members=(ONE,BEAST3,LEGEND3,MINION5,*SPELLS,FOREIGN)
    if mode=='unknown_spell':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,5,metadata(CardClass.MAGE),spell_school=SpellSchool.FIRE))
        members=(UNKNOWN,)
    if mode=='unknown_minion':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,1,metadata(tribes=('demon',),legend=True)))
        members=(UNKNOWN,)
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL,'complete-diagnostic-source-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    assembly=(FLY,CARRIER,'CORE_SW_072')
    r.register_pool(PoolDefinition(ASSEMBLY_POOL,'reviewed-diagnostic-source-pairs-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in assembly),complete=True))
    return r


class AssembleDiscoveryCopyCountTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode='normal',mana=6):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(COIN,)*12,mana=mana,max_mana=mana,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*12,mana=mana,max_mana=mana,mana_cap=30)),
            seed=413,generation_context=CTX),fixture(mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid
    def choose(self,g,key=None):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id if key is None else key,)))
    def settle(self,g):
        for _ in range(8):
            if g.state.pending_choice is None:return
            self.choose(g)
        self.fail('Unexpected unbounded source choices')
    def results(self,g,source):
        return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry)
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_seventeen_complete_rows_twenty_four_root_faces_and_inherited_cn_conflicts(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES+SKILLS+(FANATIC,));self.assertEqual(len(data['official_observations']),24)
        self.assertFalse(data['inherited_cthun_audit']['all_primary_faces_verified'])
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'])
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([f for f in json.loads(path.read_text('utf-8-sig'))['cards']if f['id']==row['record']['dbf_id']],[obs['face']])
        self.assertEqual(canonical_digest(asdict(replace(r.card(ARCHITECT),battlecry='m5.breakout_architect'))),
            rows[ARCHITECT]['historical_definition_sha256'])

    def test_explicit_native_pool_policy_changes_identity_and_preserves_default_representative(self):
        old=defaults();self.assertEqual(old.fingerprint(),DEFAULT_FP)
        self.assertEqual(old.card(ARCHITECT).battlecry,'m5.breakout_architect')
        a=defaults(version='same-domain-policy-version');b=defaults(version='same-domain-policy-version',constructed_card_spell_sources=True)
        self.assertNotEqual(a.fingerprint(),b.fingerprint())
        self.assertEqual(b.card(ARCHITECT).battlecry,'cards.breakout_architect.constructed')
        for invalid in(None,1,'yes'):
            with self.assertRaises(ValueError):defaults(constructed_card_spell_sources=invalid)

    def test_twelve_original_faces_reconstruct_and_pending_contexts_stay_explicit(self):
        r=build_registry();fingerprint=r.fingerprint();size=len(r.cards)
        for cid in SOURCES:
            derived=AssembleRecipe(cid,cid,'top').card_id
            self.assertEqual(asdict(r.card(derived)),asdict(r.card(cid))|{'id':derived})
        self.assertIsNotNone(r.card(face(LOOT,STALKER)).deathrattle)
        for cid,prefixes in((OOZE,(LOOT,END)),):
            for prefix in prefixes:
                with self.assertRaisesRegex(UnsupportedDefinitionError,'explicitly unimplemented'):r.card(face(prefix,cid))
        self.assertEqual((r.fingerprint(),len(r.cards)),(fingerprint,size))

    def test_each_twelve_suffixes_runs_from_real_paid_battlecry_with_original_quantity(self):
        for donor in SOURCES:
            with self.subTest(donor=donor):
                cid=face(FLY,donor);g=self.game(hand=(cid,ONE,BEAST3,COIN),enemy=(BIG,))
                mana=g.state.players[1].mana;eid=self.play(g,cid);self.settle(g)
                self.assertEqual(g.state.players[1].mana,mana-1)
                self.assertEqual(len(g.state.battlecry_history),1);self.assertTrue(g.state.battlecry_history[0].completed)
                self.assertEqual(g.state.battlecry_history[0].source_id,eid)
                created=self.results(g,eid)
                if donor==CARRIER:
                    self.assertEqual(len(created),1);self.assertEqual(g.state.players[1].deck[0],created[0].id)
                    self.assertEqual(quote_cost(g.state,g.registry,created[0]).amount,3)
                elif donor==RUMBLER:
                    self.assertEqual(len(g.state.ability_trigger_history),1)
                    row=g.state.ability_trigger_history[0];self.assertEqual(row.request.source.entity_id,eid)
                    self.assertEqual(row.request.battlecry_id,g.state.battlecry_history[0].id);self.assertTrue(row.completed)
                elif donor==OOZE:self.assertEqual(len(g.state.players[1].board),1)
                elif donor==ASTRO:
                    self.assertEqual(len(g.state.players[1].board),2)
                    summoned=g.state.entities[g.state.players[1].board[-1]];self.assertEqual(g.registry.card(summoned.card_id).cost,3)
                elif donor in(TORMENTOR,ENDMAW,GIFT_COPY):
                    self.assertEqual(len(created),2 if donor==GIFT_COPY else 1)
                    self.assertTrue(all(e.card_id==(LEGEND3 if donor in(TORMENTOR,GIFT_COPY)else ONE)for e in created))
                elif donor==LOWEST:
                    self.assertEqual([e.card_id for e in created],[ONE])
                elif donor==ARCHITECT:
                    self.assertEqual(len(created),1);self.assertIn(created[0].card_id,SPELLS)
                    self.assertTrue(any(a.kind=='card_spell_repeat'for a in created[0].abilities))
                elif donor==STALKER:
                    self.assertEqual(len(g.state.players[1].board),2)
                    self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[cid,cid])
                elif donor==FILL:
                    self.assertEqual(len(g.state.players[2].board),7)
                    self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
                elif donor==SCAVENGER:
                    self.assertEqual(len(created),1);self.assertEqual(g.registry.card(created[0].card_id).cost,5)

    def test_native_architect_uses_full_host_domain_and_only_generated_physical_spell_repeats(self):
        g=self.game(hand=(ARCHITECT,SPELLS[0]),mana=20);old=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==SPELLS[0])
        source=self.play(g,ARCHITECT);self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(SPELLS))
        self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==SPELLS[0]))
        new=self.results(g,source)[0];self.assertNotEqual(old,new.id);target=g.state.players[2].hero_id
        before=g.state.entities[target].health;self.play(g,SPELLS[0]);self.assertEqual(g.state.entities[target].health,before-1)
        self.play(g,SPELLS[0]);self.assertEqual(g.state.entities[target].health,before-3)
        self.assertEqual([r.source_id for r in g.state.cast_history].count(new.id),2)

    def test_real_nurturer_entry_then_discovery_deck_top_keeps_permanent_discount(self):
        cid=face(FLY,CARRIER);g=self.game(hand=(NURTURER,),mana=10);self.play(g,NURTURER)
        self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))
        source=self.play(g,cid);self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(SPELLS))
        self.choose(g);created=self.results(g,source)[0]
        self.assertEqual(g.state.players[1].deck[0],created.id)
        self.assertTrue(any(e.cost==-2 and e.expires_turn is None for e in created.enchantments))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertIn(created.id,g.state.players[1].hand)
        self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[created.id]).amount,3)

    def test_assembled_family_target_choice_restores_clones_and_replays_actual_source_and_activation(self):
        cid=face(FLY,RUMBLER);g=self.game(hand=(cid,),enemy=(BIG,));source=self.play(g,cid)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(SKILLS));self.choose(g,SKILLS[2])
        target=g.state.players[2].board[0];saved=self.portable(g)
        with self.assertRaises((IllegalAction,ResolutionError)):self.choose(g,'invalid-target')
        self.assertEqual(g.snapshot(),saved);self.choose(g,str(target))
        row=g.state.ability_trigger_history[-1]
        self.assertEqual((row.request.source.entity_id,row.request.source.card_id,row.request.target_id),(source,cid,target))
        self.assertTrue(row.completed);self.assertFalse(g.state.cast_history)
        self.assertEqual(g.state.entities[target].health,35);self.assertEqual(g.state.players[1].mana,5)
        self.assertEqual(replay(build_replay(g),fixture(self.mode,'reader')).snapshot(),g.snapshot())
        other=json.dumps(g.observe(2),ensure_ascii=False)
        for private in('rng_state','ability_trigger_history','resolution_frame'):self.assertNotIn(private,other)

    def test_death_owner_end_and_transferred_owner_start_family_choices_keep_native_windows(self):
        for prefix in(LOOT,END,START):
            with self.subTest(prefix=prefix):
                cid=face(prefix,RUMBLER);g=self.game(hand=(cid,KILL,GIVE),mana=20);source=self.play(g,cid)
                self.assertIsNone(g.state.pending_choice)
                if prefix==LOOT:self.play(g,KILL,source)
                elif prefix==END:g.apply(EndTurn(1))
                else:
                    self.play(g,GIVE,source);g.apply(EndTurn(1));self.assertEqual(g.state.pending_choice.player_id,2)
                self.choose(g,SKILLS[0]);row=g.state.ability_trigger_history[-1]
                self.assertEqual(row.request.source.entity_id,source);self.assertIsNone(row.request.battlecry_id)
                self.assertEqual(row.request.player_id,2 if prefix==START else 1);self.assertTrue(row.completed)
                if prefix==LOOT:self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_historical_battlecry_keeps_original_assembled_payload_and_new_physical_source(self):
        cid=face(FLY,RUMBLER);g=self.game(hand=(cid,KILL,HISTORY),mana=20);source=self.play(g,cid)
        self.choose(g,SKILLS[0]);self.play(g,KILL,source);borrower=self.play(g,HISTORY)
        self.choose(g,SKILLS[0]);row=g.state.ability_trigger_history[-1]
        self.assertEqual(row.request.source.entity_id,borrower);self.assertNotEqual(borrower,source)
        activation=g.state.battlecry_history[row.request.battlecry_id-1]
        self.assertEqual(activation.payload.card_id,cid);self.assertTrue(row.completed)

    def test_family_origin_requires_actual_reviewed_suffix_and_exact_battlecry_behavior(self):
        r=build_registry();profile=r.ability_family_profiles[FAMILY];cid=face(FLY,RUMBLER)
        self.assertTrue(assembled_trigger_source(r,profile,cid))
        self.assertTrue(assembled_trigger_source(r,profile,cid,battlecry_behavior=r.card(cid).battlecry))
        self.assertFalse(assembled_trigger_source(r,profile,cid,battlecry_behavior='m5.breakout_architect'))
        self.assertFalse(assembled_trigger_source(r,profile,face(RUMBLER,FLY)))
        self.assertFalse(assembled_trigger_source(r,profile,'assemble:forged'))
        self.assertFalse(assembled_trigger_source(r,profile,RUMBLER))

    def test_lowest_beast_uses_current_physical_price_and_preserves_its_copy_cost(self):
        cid=face(FLY,LOWEST);g=self.game(hand=(cid,ONE,BEAST3,DISCOUNT))
        old=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==BEAST3)
        self.play(g,DISCOUNT,old);source=self.play(g,cid);created=self.results(g,source)
        self.assertEqual([e.card_id for e in created],[BEAST3]);self.assertNotEqual(created[0].id,old)
        self.assertEqual(quote_cost(g.state,g.registry,created[0]).amount,0)

    def test_delayed_copy_reuses_timed_source_and_silence_removes_the_original_trigger(self):
        cid=face(FLY,OOZE);g=self.game(hand=(cid,),mana=20);source=self.play(g,cid)
        self.assertEqual(len(g.state.players[1].board),1);g.apply(EndTurn(1))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[cid,cid])
        g=self.game(hand=(cid,MUTE),mana=20);source=self.play(g,cid);self.play(g,MUTE,source);g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].board,[source])

    def test_unknown_eligible_members_or_missing_host_pool_rollback_native_and_assembled_entries(self):
        for mode,cid in(('no_pool',ARCHITECT),('unknown_spell',ARCHITECT),
                ('unknown_spell',face(FLY,CARRIER)),('unknown_minion',face(FLY,TORMENTOR)),
                ('unknown_minion',face(FLY,FILL))):
            with self.subTest(mode=mode,cid=cid):
                g=self.game(hand=(cid,),mode=mode,mana=20);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)

    def test_changed_full_dependency_or_skill_profile_never_partially_installs(self):
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        original=dict(r.assemble_templates)
        for cid in(ARCHITECT,SKILLS[2],FANATIC):
            old=r._cards[cid];r._cards[cid]=replace(old,name=old.name+' changed')
            try:
                with self.assertRaises(TargetValidationError):register_assemble_discovery_copy_count_fragments(r)
                self.assertEqual(dict(r.assemble_templates),original)
            finally:r._cards[cid]=old
        old_profile=r._ability_family_profiles[FAMILY]
        r._ability_family_profiles[FAMILY]=replace(old_profile,
            trigger_card_ids=tuple(cid for cid in old_profile.trigger_card_ids if cid!=RUMBLER))
        try:
            with self.assertRaises(TargetValidationError):register_assemble_discovery_copy_count_fragments(r)
            self.assertEqual(dict(r.assemble_templates),original)
        finally:r._ability_family_profiles[FAMILY]=old_profile
        register_assemble_discovery_copy_count_fragments(r)

    def test_previous_core_stamp_is_rejected_without_defaulting_new_source_rules(self):
        g=self.game();saved=g.snapshot();saved['mechanics_version']['version']='core-effects-v662'
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture(self.mode,'reader'))
