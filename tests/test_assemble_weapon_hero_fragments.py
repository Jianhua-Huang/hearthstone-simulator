"""Real weapon/Hero text on minion carriers, without whole-source side effects."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_weapon_hero_fragments import HAMMER, JARAXXUS, ELEMENTAL, BLOOD_FURY, load_batch
from hs_sim.cards.native_assemble_entry_cards import FETCHER, POOL_ID
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, recipe_from_id
from hs_sim.engine.assemble_offers import ResolveAssemble, validate_offer
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, SummonQuantitySpec, TargetSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

FLY, LOOT, DRAIN, CAIRNE = 'CORE_UNG_809', 'CORE_EX1_096', 'CORE_GIL_622', 'CORE_EX1_110'
COIN = 'GAME_005'
P = 'fixture.assemble_weapon_hero.'
KILL, MUTE, COPY, GIVE, WATCH, FAULT, MULT_SPELL, MULT_MINION = (
    P+x for x in ('kill','mute','copy','give','watch','fault','spell_quantity','minion_quantity'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('k393-reviewed-weapon-hero-fixture', 'experimental')


@lru_cache(maxsize=None)
def fixture(hero=False, mode='normal'):
    r = build_registry(); r._version += '.k393.'+str(hero)+'.'+mode
    scripts = {
        KILL: lambda c: (Destroy(c.target_id,c.source_id),),
        MUTE: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id,c.player_id,mode='current'),),
        GIVE: lambda c: (ChangeControl(c.target_id,3-c.player_id),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    def fail(c): raise ResolutionError('deliberate projected equipment fault')
    r.register_behavior(FAULT,fail)
    def watch(c):
        if c.state.entities[c.event.target_id].card_id != BLOOD_FURY: return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('weapon_equipped',WATCH),)))
    for cid,kind in ((MULT_SPELL,CardType.SPELL),(MULT_MINION,CardType.MINION)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=10,metadata=META,
            summon_quantities=(SummonQuantitySpec(factor=2,source_kinds=(kind,)),)))
    source = JARAXXUS if hero else HAMMER
    members = (LOOT,CAIRNE,JARAXXUS) if hero else (LOOT,CAIRNE,HAMMER) if mode == 'hammer_death' else (DRAIN,CAIRNE,HAMMER)
    if mode == 'missing_projection': r._assemble_projections.pop(source)
    if mode != 'missing_pool':
        r.register_pool(PoolDefinition(POOL_ID,'reviewed-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid) for cid in members),complete=True))
    return r


class AssembleWeaponHeroFragmentTests(unittest.TestCase):
    def game(self,hero=False,mode='normal',hand=(),board=()):
        own,power = ('HERO_07','HERO_07bp') if hero else ('HERO_02','HERO_02bp')
        root = MISMATCH if hero or mode == 'hammer_death' else FETCHER
        return Game.from_scenario(Scenario((
            PlayerSetup(own,hero_power_card_id=power,hand=(root,)+hand,board=board,deck=(COIN,)*12,
                mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',deck=(COIN,)*12,
                mana=30,max_mana=30,mana_cap=30)),seed=393,generation_context=CTX),fixture(hero,mode))

    def play(self,g,cid,target=None):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid,eid,target_id=target)); return eid

    def offer(self,g):
        return next(e.offer for o in g._frame.options for e in o.effects if isinstance(e,ResolveAssemble))

    def create(self,g,hero=False,half='bottom'):
        self.play(g,MISMATCH if hero else FETCHER)
        cid = AssembleRecipe(LOOT if hero else DRAIN,JARAXXUS if hero else HAMMER,half).card_id
        q = g.state.pending_choice; item = next(x for x in q.options if x.card_id == cid)
        g.apply(SelectChoice(q.player_id,q.id,(item.id,))); return cid

    def count(self,g,cid,pid=1):
        return sum(g.state.entities[i].card_id == cid for i in g.state.players[pid].board)

    def hero_header(self,g,pid=1):
        p = g.state.players[pid]; h = g.state.entities[p.hero_id]
        return p.hero_id,h.card_id,p.hero_class,h.health,h.max_health,h.armor,p.hero_power_id

    def portable(self,g,hero=False):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture.__wrapped__(hero)
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        return saved

    def test_four_complete_originals_and_eight_full_primary_faces(self):
        data = load_batch(); r = build_registry()
        rows = {x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),(HAMMER,JARAXXUS,ELEMENTAL,BLOOD_FURY))
        for cid,row in rows.items():
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        self.assertEqual(len(data['official_observations']),8)
        for x in data['official_observations']:
            kwargs = dict(display_normalizations={'~GAMEPLAY_ASPROXY_'+JARAXXUS:''}) if x['card_id'] == JARAXXUS else {}
            check_face(rows[x['card_id']]['record'],x['face'],x['locale'],**kwargs)
        self.assertEqual((rows[HAMMER]['record']['type'],rows[JARAXXUS]['record']['type']),('WEAPON','HERO'))
        self.assertIsNone(rows[JARAXXUS]['record']['attack'])
        self.assertFalse(data['cn_calibrated']); self.assertFalse(data['formal_pool_complete'])

    def test_all_compiled_halves_keep_minion_header_without_hero_or_weapon_fields(self):
        r = build_registry(); before = r.fingerprint(); inventory = tuple(r.cards)
        for first,second in ((DRAIN,HAMMER),(LOOT,JARAXXUS)):
            for half in ('top','bottom'):
                c = r.card(AssembleRecipe(first,second,half).card_id); base = r.card(first)
                self.assertEqual((c.kind,c.name,c.cost,c.attack,c.health,c.metadata),
                    (base.kind,base.name,base.cost,base.attack,base.health,base.metadata))
                self.assertFalse(c.hero_card); self.assertEqual(c.hero_armor,0)
                self.assertIsNone(c.initial_hero_power); self.assertEqual(c.durability,0)
        self.assertEqual(r.fingerprint(),before); self.assertEqual(tuple(r.cards),inventory)
        for cid in (HAMMER,JARAXXUS):
            with self.assertRaises(UnsupportedDefinitionError): r.card(AssembleRecipe(cid,FLY,'top').card_id)

    def test_jaraxxus_reuses_original_equipment_body_without_projecting_innate_hero_rules(self):
        r = build_registry(); p = r.assemble_projections[JARAXXUS]
        self.assertEqual(p.suffix.behavior_id,r.card(JARAXXUS).battlecry)
        self.assertIs(r.behavior(p.suffix.behavior_id),r.behavior(r.card(JARAXXUS).battlecry))
        self.assertEqual((r.card(JARAXXUS).hero_armor,r.card(JARAXXUS).initial_hero_power),(5,'EX1_tk33'))
        self.assertNotIn(POOL_ID,r.pools)

    def test_real_fetcher_keeps_minion_primary_and_complete_weapon_secondary_inventory(self):
        g = self.game(); source = self.play(g,FETCHER); offer = self.offer(g)
        self.assertEqual(offer.primary_candidates,(DRAIN,))
        self.assertEqual(set(offer.secondary_candidates),{CAIRNE,HAMMER})
        self.assertEqual(offer.spec.source_id,source); self.assertEqual(g.state.players[1].mana,27)
        validate_offer(g.registry,CTX,offer); self.portable(g)
        for pid in (1,2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"primary_candidates"','"secondary_candidates"','"rng_before"','"before"'):
                self.assertNotIn(key,public)

    def test_weapon_payload_is_attributed_to_minion_and_only_minion_quantity_applies(self):
        for modifier,expected in ((MULT_SPELL,1),(MULT_MINION,2)):
            with self.subTest(modifier=modifier):
                g = self.game(board=(modifier,)); cid = self.create(g); source = self.play(g,cid)
                self.assertEqual(self.count(g,ELEMENTAL),expected)
                root = g.state.card_summon_history[-1]
                self.assertEqual((root.request.cause.source.entity_id,root.request.cause.source.card_id,
                    root.request.cause.source.kind),(source,cid,CardType.MINION))
                self.assertIsNone(g.state.players[1].weapon_id)

    def test_weapon_deathrattle_prefix_executes_original_minion_payload_only_on_death(self):
        g = self.game(hand=(KILL,)); cid = self.create(g,half='top')
        before = g.state.entities[g.state.players[2].hero_id].health
        source = self.play(g,cid)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,before)
        self.play(g,KILL,source)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,before-3)
        self.assertEqual(self.count(g,ELEMENTAL),0); self.assertIsNone(g.state.players[1].weapon_id)

    def test_borrowed_weapon_payload_uses_actual_minion_death_slot_between_survivors(self):
        g = self.game(mode='hammer_death',hand=(KILL,),board=(FLY,))
        left = g.state.players[1].board[0]; right = self.play(g,MISMATCH)
        cid = AssembleRecipe(LOOT,HAMMER,'bottom').card_id
        q = g.state.pending_choice; item = next(x for x in q.options if x.card_id == cid)
        g.apply(SelectChoice(1,q.id,(item.id,)))
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1,source,position=1))
        self.assertEqual(g.state.players[1].board,[left,source,right])
        self.play(g,KILL,source)
        token = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == ELEMENTAL)
        self.assertEqual(g.state.players[1].board,[left,token,right])
        root = g.state.card_summon_history[-1]
        self.assertEqual((root.request.position,root.request.cause.source.entity_id,root.request.cause.source.kind),
            (1,source,CardType.MINION))

    def test_hero_battlecry_prefix_draws_without_armor_hero_or_power_replacement(self):
        g = self.game(hero=True); header = self.hero_header(g)
        cid = self.create(g,hero=True,half='top'); before = len(g.state.players[1].hand)
        self.play(g,cid)
        self.assertEqual(len(g.state.players[1].hand),before)
        self.assertEqual(self.hero_header(g),header); self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.players[1].mana,23)

    def test_hero_equipment_suffix_waits_for_minion_death_and_keeps_hero_power(self):
        g = self.game(hero=True,hand=(KILL,)); header = self.hero_header(g)
        cid = self.create(g,hero=True); source = self.play(g,cid)
        self.assertIsNone(g.state.players[1].weapon_id)
        cursor = len(g.events); self.play(g,KILL,source)
        weapon = g.state.entities[g.state.players[1].weapon_id]
        self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),(BLOOD_FURY,3,8))
        self.assertEqual(self.hero_header(g),header)
        self.assertFalse(any(e.kind == 'hero_power_replaced' for e in g.events[cursor:]))
        self.portable(g,hero=True)

    def test_projected_equipment_retires_old_real_weapon_and_executes_its_own_deathrattle(self):
        g = self.game(hero=True,hand=(HAMMER,KILL)); old_weapon = self.play(g,HAMMER)
        cid = self.create(g,hero=True); source = self.play(g,cid); header = self.hero_header(g)
        self.play(g,KILL,source)
        self.assertEqual(g.state.entities[old_weapon].zone,Zone.GRAVEYARD)
        self.assertEqual(self.count(g,ELEMENTAL),1)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,BLOOD_FURY)
        self.assertEqual(self.hero_header(g),header)

    def test_full_board_uses_original_summon_capacity_without_materializing_a_weapon(self):
        g = self.game(board=(FLY,)*5); cid = self.create(g); self.play(g,cid)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(self.count(g,ELEMENTAL),0)
        self.assertIsNone(g.state.players[1].weapon_id)

    def test_copied_native_deathrattle_equips_and_silenced_original_does_not(self):
        g = self.game(hero=True,hand=(COPY,MUTE,KILL,KILL)); cid = self.create(g,hero=True)
        source = self.play(g,cid); self.play(g,COPY,source)
        copied = next(i for i in g.state.players[1].board if i != source and g.state.entities[i].card_id == cid)
        self.play(g,MUTE,source); self.play(g,KILL,source)
        self.assertIsNone(g.state.players[1].weapon_id)
        header = self.hero_header(g); self.play(g,KILL,copied)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,BLOOD_FURY)
        self.assertEqual(self.hero_header(g),header)

    def test_control_change_equips_for_actual_deathrattle_controller(self):
        g = self.game(hero=True,hand=(GIVE,KILL)); cid = self.create(g,hero=True)
        source = self.play(g,cid); self.play(g,GIVE,source)
        old = (self.hero_header(g),self.hero_header(g,2)); self.play(g,KILL,source)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[g.state.players[2].weapon_id].card_id,BLOOD_FURY)
        self.assertEqual((self.hero_header(g),self.hero_header(g,2)),old)

    def test_equipment_reaction_wait_restore_replay_and_failed_resume_keep_original_boundary(self):
        g = self.game(hero=True,board=(WATCH,),hand=(KILL,)); cid = self.create(g,hero=True)
        source = self.play(g,cid); self.play(g,KILL,source)
        saved = self.portable(g,hero=True); q = g.state.pending_choice
        self.assertIsNotNone(q)
        with self.assertRaisesRegex(ResolutionError,'deliberate projected equipment fault'):
            g.apply(SelectChoice(q.player_id,q.id,('fault',)))
        self.assertEqual(g.snapshot(),saved)
        g.apply(SelectChoice(q.player_id,q.id,('ok',))); self.portable(g,hero=True)

    def test_missing_projection_or_domain_rolls_back_whole_original_paid_assembly(self):
        for hero in (False,True):
            for mode in ('missing_projection','missing_pool'):
                with self.subTest(hero=hero,mode=mode):
                    g = self.game(hero=hero,mode=mode); before = g.snapshot()
                    with self.assertRaises(ValueError): self.play(g,MISMATCH if hero else FETCHER)
                    self.assertEqual(g.snapshot(),before)

    def test_complete_original_pins_and_saved_registry_material_cannot_be_substituted(self):
        r = build_registry(); p = r.assemble_projections[HAMMER]
        with self.assertRaises(ValueError): r.register_assemble_projection(replace(p,definition_sha256='0'*64))
        g = self.game(); self.play(g,FETCHER); saved = g.snapshot()
        reader = fixture.__wrapped__(); reader._assemble_projections.pop(HAMMER)
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved,reader)


if __name__ == '__main__': unittest.main()
