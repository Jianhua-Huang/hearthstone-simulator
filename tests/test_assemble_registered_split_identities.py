"""Physical identities stay separate; actual reviewed producers exercise them."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import assemble_registered_split_identities as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import NURTURER, POOL_ID
from hs_sim.engine import (Attack, BoardPresenceReference, CardClass, CardDefinition,
    CardMetadata, CardType, EndTurn, Game, Keyword, PlayerSetup, Scenario, SelectChoice,
    SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, validate_template
from hs_sim.engine.assemble_offers import draw
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, ForceAttack,
    GainArmor, Heal, InvokeBehavior, RequestChoice, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

BASE, LOOT, CAIRNE, COIN, FLAME = 'CORE_UNG_809', 'CORE_EX1_096', 'CORE_EX1_110', 'GAME_005', 'UNG_809t1'
PIRATE, BEAST, MAGE = 'KAR_069', 'CORE_GIL_622', 'CS2_028'
P = 'fixture.registered_split.'
KILL, HIT, FORCE, DEFEND, MARKER, ACTIVE, HEAL, NOOP, UNDEAD, ENEMY, WEAPON, WATCH, FAIL = (
    P+key for key in ('kill','hit','force','defend','marker','active','heal','noop','undead','enemy','weapon','watch','fail'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
HEROES = dict(zip((CardClass.WARRIOR, CardClass.SHAMAN, CardClass.ROGUE, CardClass.PALADIN,
    CardClass.HUNTER, CardClass.DRUID, CardClass.WARLOCK, CardClass.MAGE, CardClass.PRIEST,
    CardClass.DEMON_HUNTER, CardClass.DEATH_KNIGHT), ('HERO_01','HERO_02','HERO_03','HERO_04',
    'HERO_05','HERO_06','HERO_07','HERO_08','HERO_09','HERO_10','HERO_11')))


def context(cid):
    return GenerationContext('k524-physical-source-'+cid, 'experimental')


def root(cid, registry):
    return MISMATCH if registry.card(cid).cost >= 5 else NURTURER


def setups(registry, cid, mode='normal', actor=1, extra=()):
    cls = registry.card(cid).metadata.classes[0]
    hero = HEROES.get(cls, 'HERO_08')
    return tuple(PlayerSetup(hero if player == actor else 'HERO_08',
        hand=(root(cid, registry), KILL, HIT, FORCE, DEFEND, MARKER, ACTIVE, HEAL)+extra if player == actor else (),
        board=(UNDEAD, WATCH) if player == actor and mode in ('wait','fail') else
            (UNDEAD,) if player == actor else (ENEMY,),
        deck=(COIN,)*20, weapon_card_id=WEAPON if player == actor else None,
        mana=30, max_mana=30, mana_cap=30) for player in (1,2))


def fixture(mode='normal', role='writer'):
    return cached_fixture(mode, role)


@lru_cache(maxsize=None)
def cached_fixture(mode, role):
    r = build_registry()
    r._version += '.k524.physical.'+mode
    target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        HEAL: lambda c: (Heal(c.target_id, 1, c.source_id),),
        FORCE: lambda c: (ForceAttack(BoardPresenceReference.capture(c.state, c.target_id),
            c.state.players[3-c.player_id].hero_id),),
        DEFEND: lambda c: (ForceAttack(next(i for i in c.state.players[3-c.player_id].board
            if c.state.entities[i].card_id == ENEMY), BoardPresenceReference.capture(c.state, c.target_id)),),
        ACTIVE: lambda c: (TriggerDeathrattles(c.target_id, c.source_id),),
        MARKER: lambda c: (AddToHand(c.player_id, NOOP, c.source_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec() if cid in (HIT,HEAL) else None if cid == MARKER else target))
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, on_play=NOOP, metadata=META))
    r.register_card(CardDefinition(UNDEAD, UNDEAD, CardType.MINION, health=10,
        metadata=replace(META, tribes=('undead',))))
    r.register_card(CardDefinition(ENEMY, ENEMY, CardType.MINION, attack=1, health=12, metadata=META))
    r.register_card(CardDefinition(WEAPON, WEAPON, CardType.WEAPON, attack=1, durability=3, metadata=META))

    def fail(c):
        raise ResolutionError('deliberate physical source draw failure')

    def watch(c):
        if c.event.player_id != c.player_id:
            return ()
        effects = (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))
        if mode == 'fail':
            return effects
        return (RequestChoice(c.player_id, (ChoiceOption('continue','Continue'),
            ChoiceOption('bad','Fail',effects)), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=10, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    for cid in cards.SOURCES:
        domain = (BASE, cid, CAIRNE if r.card(cid).cost >= 5 else LOOT)
        ctx = context(cid)
        r.register_pool(PoolDefinition(POOL_ID, 'three-complete-physical-sources-v1',
            ctx.target_id, ctx.mode, tuple(PoolMember(card) for card in domain), complete=True))
        r.register_pool(PoolDefinition('constructed.cards', 'three-known-diagnostic-generation-facts-v1',
            ctx.target_id, ctx.mode, tuple(PoolMember(card) for card in (PIRATE,BEAST,MAGE)), complete=True))
    # Preflight the exact public producer with a copy of its untouched RNG. This
    # finds deterministic seeds when more than one real one-cost primary exists.
    plans = {}
    for cid in cards.SOURCES if mode == 'normal' else ('EX1_007',):
        for seed in range(32):
            g = Game.from_scenario(Scenario(setups(r,cid,mode), seed=seed, generation_context=context(cid)),r)
            source = g.state.players[1].hand[0]
            original = r.card(root(cid,r))
            request = r.behavior(original.on_play or original.battlecry)(RuleContext(g._state,source,1))[0]
            rng = Random(); rng.setstate(g._rng.getstate())
            selection = draw(r,context(cid),g._state,request,rng)
            if selection[1] == BASE and cid in selection[3]:
                plans[cid] = dict(seed=seed,root=root(cid,r),primary=BASE,
                    complete_secondaries=list(selection[2]),selected_secondaries=list(selection[3]))
                break
        if cid not in plans:
            raise AssertionError('No actual producer domain for '+cid)
    return r, plans


class RegisteredSplitIdentityTests(CardBatchTestMixin, unittest.TestCase):
    def registry_factory(self, mode, role):
        return fixture(mode,role)[0]

    def game(self,cid,mode='normal',actor=1,extra=()):
        self.mode, self.cid = mode, cid
        r,plans = fixture(mode)
        return Game.from_scenario(Scenario(setups(r,cid,mode,actor,extra), active_player=actor,
            seed=plans[cid]['seed'],generation_context=context(cid)),r)

    def play(self,g,cid,target=None):
        return super().play(g,cid,target,player=g.state.active_player)

    def manufacture(self,g,half='bottom'):
        self.play(g,root(self.cid,g.registry))
        q = g.state.pending_choice
        cid = AssembleRecipe(BASE,self.cid,half).card_id
        chosen = next(x for x in q.options if x.card_id == cid)
        g.apply(SelectChoice(q.player_id,q.id,(chosen.id,)))
        return cid

    def hand_count(self,g,cid,player=1):
        return sum(g.state.entities[i].card_id == cid for i in g.state.players[player].hand)

    def test_fifteen_whole_identities_sixty_four_primary_faces_and_exact_original_programs(self):
        d=cards.load_batch();r,_=fixture();responses={}
        rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual(len(d['official_observations']),64)
        for obs in d['official_observations']:
            path=Path(obs['response_file'])
            if str(path) not in responses:
                self.assertEqual(batch.sha(path),obs['response_sha256'])
                responses[str(path)]={face['id']:face for face in json.loads(path.read_text(encoding='utf-8-sig'))['cards']}
            self.assertEqual(responses[str(path)][obs['face']['id']],obs['face'])
            batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'])
        for cid,row in rows.items():
            self.assertEqual(batch.canonical(asdict(r.card(cid))),row['definition_sha256'])
        for item in d['reviewed_sources']:
            cid,core=item['card_id'],item['core_id'];validate_template(r,r.assemble_templates[cid])
            self.assertNotEqual(cid,core)
            if item['native_body_slot'] in ('battlecry','combo'):
                self.assertEqual(r.assemble_templates[cid].suffix.behavior_id,getattr(r.card(cid),item['native_body_slot']))
        with patch.object(cards,'BATCH_HASH','0'*64),self.assertRaises(TargetValidationError):cards.load_batch()

    def test_fifteen_borrowed_bodies_use_actual_producers_and_keep_primary_material(self):
        for source in cards.SOURCES:
            with self.subTest(source=source):
                g=self.game(source);cid=self.manufacture(g);actor=g.state.players[1]
                mana=actor.mana;hero=g.state.players[2].hero_id;enemy=self.entity(g,ENEMY,2,zone='board').id
                before_health=g.state.entities[hero].health+g.state.entities[enemy].health
                before_attack=sum(g.state.entities[i].attack for i in actor.board)
                eid=self.play(g,cid);entity=g.state.entities[eid]
                self.assertEqual(g.state.players[1].mana,mana-1)
                self.assertEqual(g.registry.card(cid).metadata,g.registry.card(BASE).metadata)
                if source in ('BAR_313','RLK_814'):
                    n=3 if source=='BAR_313'else 1
                    self.assertEqual((entity.attack,entity.max_health),(1+n,2+n))
                elif source=='BT_351':self.assertEqual(entity.attack,2)
                elif source in ('BT_480','EX1_007','RLK_121'):
                    self.assertEqual(len([x for x in g.state.draw_history if x.source_id==eid]),1)
                elif source=='BT_493':
                    self.assertEqual(before_health-g.state.entities[hero].health-g.state.entities[enemy].health,6)
                elif source=='BT_510':
                    self.assertEqual((g.state.entities[hero].health,g.state.entities[enemy].health),(29,11))
                elif source=='DMF_067':
                    self.assertEqual(self.hand_count(g,COIN,1),1);self.assertEqual(self.hand_count(g,COIN,2),1)
                elif source in ('DRG_024','KAR_069','UNG_912'):
                    self.assertEqual(self.hand_count(g,dict(DRG_024=PIRATE,KAR_069=MAGE,UNG_912=BEAST)[source]),1)
                elif source=='EX1_131':
                    self.assertEqual(sum(g.state.entities[i].card_id==cards.TOKEN for i in g.state.players[1].board),1)
                    self.assertFalse(g.state.combo_history)
                elif source=='WC_701':
                    self.assertEqual((g.state.entities[hero].health,g.state.entities[enemy].health),(30,11))
                else:self.assertEqual(sum(g.state.entities[i].attack for i in g.state.players[1].board),before_attack+2)
                self.assertEqual(self.hand_count(g,FLAME),0)

    def test_reaction_prefixes_bind_the_old_physical_source_and_original_event(self):
        for source in ('BT_351','BT_510','EX1_007','RLK_121'):
            with self.subTest(source=source):
                g=self.game(source);cid=self.manufacture(g,'top');eid=self.play(g,cid)
                if source=='BT_351':g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
                elif source=='BT_510':
                    self.play(g,FORCE,eid);self.assertEqual(self.hand_count(g,FLAME),0)
                    self.play(g,DEFEND,eid)
                elif source=='EX1_007':self.play(g,HIT,eid)
                else:self.play(g,KILL,self.entity(g,UNDEAD,zone='board').id)
                self.assertEqual(self.hand_count(g,FLAME),1)

    def test_conditional_prefixes_keep_the_heal_and_held_shadow_gates(self):
        for source in ('BAR_313','RLK_814'):
            for enabled in (False,True):
                with self.subTest(source=source,enabled=enabled):
                    r,_=fixture();shadow=next(cid for cid,c in r.cards.items() if c.kind==CardType.SPELL and c.spell_school==SpellSchool.SHADOW)
                    g=self.game(source,extra=(shadow,) if source=='RLK_814'and enabled else ())
                    if source=='BAR_313'and enabled:
                        hero=g.state.players[1].hero_id;self.play(g,HIT,hero);self.play(g,HEAL,hero)
                    cid=self.manufacture(g,'top');self.play(g,cid)
                    self.assertEqual(self.hand_count(g,FLAME),int(enabled))

    def test_outcast_prefix_uses_actual_edge_and_combo_prefix_uses_actual_turn(self):
        for source in ('BT_480','EX1_131'):
            for enabled in (False,True):
                with self.subTest(source=source,enabled=enabled):
                    g=self.game(source);cid=self.manufacture(g,'top')
                    if not enabled:
                        if source=='BT_480':self.play(g,MARKER)
                        else:g.apply(EndTurn(1));g.apply(EndTurn(2))
                    self.play(g,cid);self.assertEqual(self.hand_count(g,FLAME),int(enabled))

    def test_owner_end_dual_and_death_prefixes_keep_their_actual_lifetimes(self):
        for source in ('BT_493','DMF_067','WC_701','YOD_026'):
            with self.subTest(source=source):
                g=self.game(source);cid=self.manufacture(g,'top');eid=self.play(g,cid)
                self.assertEqual(self.hand_count(g,FLAME),int(source=='DMF_067'))
                if source=='BT_493':g.apply(EndTurn(1))
                else:self.play(g,KILL,eid)
                self.assertEqual(self.hand_count(g,FLAME),2 if source=='DMF_067'else 1)

    def test_opponent_actor_and_waiting_draw_restore_clone_replay_and_reject_bad_resume(self):
        g=self.game('KAR_069',actor=2);cid=self.manufacture(g);self.play(g,cid)
        self.assertEqual(self.hand_count(g,MAGE,2),1)
        g=self.game('EX1_007','wait');cid=self.manufacture(g);self.play(g,cid)
        saved=json.loads(json.dumps(g.snapshot()));r=fixture('wait','reader')[0]
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        legs=(g,Game.from_snapshot(saved,r),g.clone(),replay(build_replay(g),r))
        for leg in legs:self.choose(leg)
        self.assertTrue(all(leg.snapshot()==g.snapshot()for leg in legs))
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for field in ('rng_state','resolution_frame','hand_entry_id'):self.assertNotIn('"'+field+'"',view)

    def test_late_draw_failure_rolls_back_payment_source_draw_and_original_assemble_history(self):
        g=self.game('EX1_007','fail');cid=self.manufacture(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),before)

    def test_death_body_amendment_is_pinned_additive_atomic_and_frozen(self):
        r=build_registry();original=r.card('EX1_131');cid=P+'reviewed_combo_source'
        r.register_card(replace(original,id=cid,metadata=META))
        t=replace(r.assemble_templates['EX1_131'],card_id=cid,
            suffix=replace(r.assemble_templates['EX1_131'].suffix,deathrattle_behavior_id=None))
        r.register_assemble_template(t);pin=canonical_hash(asdict(t))
        for key,body in [('0'*64,cards.DEATH_BODY),(pin,P+'missing_body')]:
            with self.assertRaises(ValueError):r.set_assemble_suffix_deathrattle_body(cid,body,expected_template_sha256=key)
            self.assertEqual(r.assemble_templates[cid],t)
        r.set_assemble_suffix_deathrattle_body(cid,cards.DEATH_BODY,expected_template_sha256=pin)
        updated=r.assemble_templates[cid]
        self.assertEqual(replace(updated,suffix=replace(updated.suffix,deathrattle_behavior_id=None)),t)
        with self.assertRaises(ValueError):r.set_assemble_suffix_deathrattle_body(cid,cards.DEATH_BODY,expected_template_sha256=canonical_hash(asdict(updated)))
        Game.from_scenario(Scenario((PlayerSetup('HERO_08'),PlayerSetup('HERO_08'))),r)
        with self.assertRaises((ValueError,RuntimeError)):r.set_assemble_suffix_deathrattle_body(cid,cards.DEATH_BODY,expected_template_sha256=canonical_hash(asdict(updated)))


if __name__=='__main__':unittest.main()
