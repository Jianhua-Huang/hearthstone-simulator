"""P06 original hand commitments, accepted costs and visible next-owner Objective."""
from dataclasses import asdict, replace
import json
import re
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_timing_p06_cards import (
    WEBWEAVER, MAGMA, FLOCK, HATCHLING, ROOTS, PREFIX, load_batch,
    register_simple_timing_p06_cards,
)
from hs_sim.engine import (
    CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, IllegalAction,
    PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone,
)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (
    AddToHand, ChoiceOption, Damage, Destroy, Draw, InvokeBehavior, ModifyCost,
    RequestChoice, ReturnToHand, Silence, Transform,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import CostSpec, DamageKind, PaymentType, SpellSchool
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST = 'p06.test.'
YETI = 'CORE_CS2_182'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


def registry():
    r = build_registry()
    present = tuple(cid in r.cards for cid in ROOTS)
    if any(present) and not all(present):raise AssertionError('Partial P06 registration')
    if not all(present):register_simple_timing_p06_cards(r)

    def summon(c, cid):
        return SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c))

    def modify(c, spec):
        e = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                 if c.state.entities[i].card_id == TEST+'fire')
        return (ModifyCost(e.id, spec, c.source_id),)

    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id, cause=SummonCause.capture(c)),)

    def wait(c, extra=()):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST+'fail', c.source_id, c.player_id),)),
            *extra,
        ), c.source_id),)

    def commit_wait(c):
        if c.event.player_id != c.player_id or c.state.entities[c.event.source_id].card_id not in (TEST+'fire', TEST+'plain'):
            return ()
        magma = next((c.state.entities[i] for i in c.state.players[c.player_id].board
                      if c.state.entities[i].card_id == MAGMA), None)
        extra = () if magma is None else (
            ChoiceOption('bounce', 'Return and reenter original Magma', (
                ReturnToHand(magma.id), InvokeBehavior(TEST+'reenter', c.source_id, c.player_id, magma.id))),
            ChoiceOption('kill', 'Destroy original Magma', (Destroy(magma.id, c.source_id),)),
        )
        return wait(c, extra)

    def hatch_wait(c):
        if (c.event.player_id != c.player_id or c.state.entities[c.event.target_id].card_id != HATCHLING or
                sum(c.state.entities[i].card_id == HATCHLING for i in c.state.players[c.player_id].board) != 1):
            return ()
        return wait(c)

    def counter(c):
        return (CounterMinion(dict(c.event.data)['window_id']),) if (
            c.event.player_id != c.player_id and c.state.entities[c.event.source_id].kind == CardType.MINION) else ()

    def fill_hand(c):
        if c.event.player_id != c.player_id or c.state.entities[c.event.source_id].card_id != TEST+'plain':return ()
        if sum(x.player_id==c.player_id and x.card_id==TEST+'plain' for x in c.state.play_history)!=2:return ()
        return (AddToHand(c.player_id,YETI,c.source_id),)*2

    scripts = {
        'summon': lambda c: (summon(c, TEST+'plain'),),
        'auto_fire': lambda c: (CastSpell(c.player_id, TEST+'fire', c.source_id),),
        'auto_flock': lambda c: (CastSpell(2, FLOCK, c.source_id),),
        'reduce': lambda c: modify(c, CostSpec(delta=-2)),
        'free': lambda c: modify(c, CostSpec(set_to=0)),
        'health': lambda c: modify(c, CostSpec(set_to=3, payment=PaymentType.HEALTH)),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'transform': lambda c: (Transform(c.target_id, TEST+'plain'),),
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'skip': lambda c: (SkipTurns(2, 1, c.source_id),),
        'extra': lambda c: (QueueTurns((1, 2), c.source_id),),
        'fire': lambda c: (),
        'fire_hit': lambda c: (Damage(c.target_id, 8, c.source_id, DamageKind.SPELL),),
        'nature': lambda c: (),
    }
    for name, body in scripts.items():
        key = TEST+name;r.register_behavior(key, body)
        school = SpellSchool.FIRE if name.startswith('fire') else SpellSchool.NATURE if name == 'nature' else None
        r.register_card(CardDefinition(key, name, CardType.SPELL, cost=5 if name=='fire' else 4 if name=='fire_hit' else 0,
            on_play=key, spell_school=school, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
                if name in ('kill','silence','bounce','transform','fire_hit') else None))
    for name, identity in (('plain', TEST+'plain'), ('other', TEST+'other'), ('alias_a', 'P06.original'), ('alias_b', 'P06.original')):
        r.register_card(CardDefinition(TEST+name, name, CardType.MINION, attack=1, health=3,
            metadata=replace(META, deck_identity=identity)))
    r.register_behavior(TEST+'check_draw', lambda c: (Damage(c.state.players[2].hero_id,
        len(c.state.players[c.player_id].hand), c.source_id, DamageKind.MINION_ABILITY),))
    r.register_card(CardDefinition(TEST+'battlecry', 'Draw timing probe', CardType.MINION, health=2,
        battlecry=TEST+'check_draw', metadata=replace(META, deck_identity=TEST+'plain')))
    r.register_behavior(TEST+'reenter', reenter)
    r.register_behavior(TEST+'fail', lambda c: (AddToHand(c.player_id, 'p06.missing'),))
    def late_flock(c):
        return (CastSpell(1, FLOCK, c.source_id),) if c.event.player_id==1 and c.state.turn==3 else ()
    for name, event, body in (
        ('commit_wait', 'card_committed', commit_wait),
        ('hatch_wait', 'minion_summoned', hatch_wait),
        ('counter', 'card_committed', counter),
        ('fill_hand', 'card_committed', fill_hand),
        ('late_flock', 'turn_started', late_flock),
    ):
        key=TEST+name;r.register_behavior(key, body)
        r.register_card(CardDefinition(key, name, CardType.MINION, health=9, metadata=META,
            triggers=(TriggerSpec(event, key),)))
    r.validate();return r


class SimpleTimingP06CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()

    def game(self, hand=(), board=(), enemy=(), *, enemy_hand=(), active=1, deck=(YETI,)*14):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=40, max_mana=40, mana_cap=40,
                hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*14, mana=40, max_mana=40, mana_cap=40,
                hero_power_card_id='HERO_08bp'),
        ), active_player=active, seed=606), self.r)

    def entities(self,g,cid,p=1,zone='board'):
        return [g.state.entities[i] for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;source=self.first(g,cid,p,'hand').id
        g.apply(PlayCard(p,source,target,len(g.state.players[p].board) if self.r.card(cid).kind==CardType.MINION else None));return source
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def cycle(self,g):self.end(g);self.end(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def stats(self,g):
        e=self.first(g,MAGMA);return e.attack,e.health
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for hidden in('rng_state','resolution_frame','CardReference','MinionReference','submitted_cost','played_face','behavior_id'):
                self.assertNotIn(hidden,public)
        return other

    def test_complete_raw_and_official_faces_existing_exact_hatchling(self):
        d=load_batch();self.assertEqual(tuple(x['record']['id']for x in d['cards']),ROOTS)
        self.assertFalse(d['dependencies']);self.assertFalse(d['skipped'])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        self.assertEqual(len(d['official_observations']['observations']),8)
        def normalize(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['existing_dependencies']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in (o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                face=o['face'];en=o['locale']=='en-us'
                self.assertEqual(face['name'],raw['name_en'if en else'name'])
                self.assertEqual(normalize(face['text']),normalize(raw['text_en'if en else'text']))
                for k,v in(('id',raw['dbf_id']),('manaCost',raw['cost']),('cardSetId',raw['card_set_id']),
                            ('classId',raw['tags']['CLASS']),('cardTypeId',raw['tags']['CARDTYPE'])):self.assertEqual(face[k],v)
                if raw['type']=='MINION':self.assertEqual((face['attack'],face['health']),(raw['attack'],raw['health']))
            if raw['id']in ROOTS:self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
        dep,=d['existing_dependencies'];self.assertEqual(canonical_digest(asdict(self.r.card(HATCHLING))),dep['definition_sha256'])
        self.assertEqual((self.r.card(HATCHLING).cost,self.r.card(HATCHLING).attack,self.r.card(HATCHLING).health),(1,2,1))
        self.assertEqual(set(self.r.card(MAGMA).metadata.tribes),{'elemental','mech'})

    def test_default_registry_stays_311_and_same_fingerprint(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311)
        self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_each_root_actual_hand_play_pays_once_and_installs_exact_body(self):
        for cid in ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,));eid=self.play(g,cid);definition=self.r.card(cid)
                self.assertEqual(g.state.players[1].mana,40-definition.cost)
                self.assertEqual(len(g.state.play_history),1);self.assertTrue(g.state.play_history[0].completed)
                if cid!=FLOCK:self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(definition.attack,definition.health))
                else:self.assertEqual(self.r.player_effect(g.state.players[1].player_effects[0].spec_id).kind,'objective')

    def test_webweaver_first_different_and_repeat_prior_minion(self):
        g=self.game((TEST+'plain',TEST+'other',TEST+'plain'),(WEBWEAVER,));deck=len(g.state.players[1].deck)
        self.play(g,TEST+'plain');self.play(g,TEST+'other');self.assertEqual(len(g.state.players[1].deck),deck)
        self.play(g,TEST+'plain');self.assertEqual(len(g.state.players[1].deck),deck-1);self.portable(g)

    def test_webweaver_never_uses_current_play_as_its_own_prior_history(self):
        g=self.game((WEBWEAVER,TEST+'plain'));self.play(g,WEBWEAVER);self.play(g,TEST+'plain')
        self.assertEqual(len(g.state.players[1].deck),14)

    def test_webweaver_second_physical_listener_can_trigger_first_once(self):
        g=self.game((WEBWEAVER,WEBWEAVER));self.play(g,WEBWEAVER);self.play(g,WEBWEAVER)
        self.assertEqual(len(g.state.players[1].deck),13);self.assertEqual(len(self.entities(g,WEBWEAVER)),2)

    def test_webweaver_frozen_canonical_identity_matches_explicit_aliases(self):
        g=self.game((TEST+'alias_a',TEST+'alias_b'),(WEBWEAVER,));self.play(g,TEST+'alias_a');self.play(g,TEST+'alias_b')
        self.assertEqual(len(g.state.players[1].deck),13);self.portable(g)

    def test_webweaver_previous_own_turn_is_included(self):
        g=self.game((TEST+'plain',TEST+'plain'),(WEBWEAVER,));self.play(g,TEST+'plain');self.cycle(g)
        before=len(g.state.players[1].deck);self.play(g,TEST+'plain');self.assertEqual(len(g.state.players[1].deck),before-1)

    def test_webweaver_enemy_play_does_not_supply_personal_history(self):
        g=self.game((TEST+'plain',),(WEBWEAVER,),enemy_hand=(TEST+'plain',),active=2)
        self.play(g,TEST+'plain');self.end(g);before=len(g.state.players[1].deck);self.play(g,TEST+'plain')
        self.assertEqual(len(g.state.players[1].deck),before)

    def test_webweaver_summon_and_transform_are_not_prior_plays(self):
        g=self.game((TEST+'summon',TEST+'transform',TEST+'plain'),(WEBWEAVER,TEST+'other'))
        self.play(g,TEST+'summon');self.play(g,TEST+'transform',self.first(g,TEST+'other').id)
        self.play(g,TEST+'plain');self.assertEqual(len(g.state.players[1].deck),14)

    def test_webweaver_prior_play_identity_survives_later_transform(self):
        g=self.game((TEST+'alias_a',TEST+'transform',TEST+'alias_b'),(WEBWEAVER,));eid=self.play(g,TEST+'alias_a')
        self.play(g,TEST+'transform',eid);self.play(g,TEST+'alias_b')
        self.assertEqual(len(g.state.players[1].deck),13);self.portable(g)

    def test_webweaver_draw_precedes_current_battlecry_payload(self):
        g=self.game((TEST+'plain',TEST+'battlecry'),(WEBWEAVER,));self.play(g,TEST+'plain');self.play(g,TEST+'battlecry')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29)

    def test_webweaver_countered_committed_minions_count_and_trigger(self):
        g=self.game((TEST+'plain',TEST+'plain'),(WEBWEAVER,),(TEST+'counter',))
        self.play(g,TEST+'plain');self.play(g,TEST+'plain')
        self.assertEqual([x.countered for x in g.state.play_history],[True,True])
        self.assertFalse(self.entities(g,TEST+'plain'));self.assertEqual(len(g.state.players[1].deck),13);self.portable(g)

    def test_webweaver_draw_burns_at_hand_capacity_and_fatigues_normally(self):
        g=self.game((TEST+'plain',TEST+'plain'),(WEBWEAVER,),deck=())
        self.play(g,TEST+'plain');self.play(g,TEST+'plain')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29)
        g=self.game((TEST+'plain',TEST+'plain',*(YETI,)*8),(TEST+'fill_hand',WEBWEAVER))
        self.play(g,TEST+'plain');self.play(g,TEST+'plain');self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len(g.state.players[1].deck),13)
        self.assertEqual(sum(e.kind=='card_burned'for e in g.events),1);self.portable(g)

    def test_magma_current_discounted_quote_is_three_not_printed_five(self):
        g=self.game((TEST+'reduce',TEST+'fire'),(MAGMA,));self.play(g,TEST+'reduce');self.play(g,TEST+'fire')
        self.assertEqual(self.stats(g),(5,8));self.assertEqual(g.state.play_history[-1].submitted_cost.quote.amount,3)
        self.assertEqual(g.state.players[1].mana,37);self.portable(g)

    def test_magma_zero_cost_fire_does_not_gain_printed_stats(self):
        g=self.game((TEST+'free',TEST+'fire'),(MAGMA,));self.play(g,TEST+'free');self.play(g,TEST+'fire')
        self.assertEqual(self.stats(g),(2,5));self.assertEqual(g.state.players[1].mana,40)

    def test_magma_health_payment_uses_quote_not_zero_mana_debit(self):
        g=self.game((TEST+'health',TEST+'fire'),(MAGMA,));self.play(g,TEST+'health');self.play(g,TEST+'fire')
        self.assertEqual(self.stats(g),(5,8));self.assertEqual(g.state.players[1].mana,40)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)
        record=g.state.play_history[-1];self.assertEqual((record.cost,record.payment),(3,PaymentType.HEALTH))
        self.portable(g)

    def test_magma_buff_precedes_fire_payload_and_can_keep_source_alive(self):
        g=self.game((TEST+'fire_hit',),(MAGMA,));source=self.first(g,MAGMA).id;self.play(g,TEST+'fire_hit',source)
        self.assertEqual(self.stats(g),(6,1));self.assertEqual(g.state.entities[source].zone,Zone.BOARD)

    def test_magma_other_school_and_automatic_fire_do_not_count_as_hand_play(self):
        g=self.game((TEST+'nature',TEST+'auto_fire'),(MAGMA,));self.play(g,TEST+'nature');self.play(g,TEST+'auto_fire')
        self.assertEqual(self.stats(g),(2,5));self.assertEqual(g.state.cast_history[-1].origin,'effect')
        self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_magma_enemy_fire_does_not_trigger(self):
        g=self.game(board=(MAGMA,),enemy_hand=(TEST+'fire',),active=2);self.play(g,TEST+'fire')
        self.assertEqual(self.stats(g),(2,5))

    def test_magma_countered_hand_fire_still_gains_accepted_quote(self):
        g=self.game((TEST+'fire',),(MAGMA,),enemy_hand=('EX1_287',),active=2)
        self.play(g,'EX1_287');self.end(g);self.play(g,TEST+'fire')
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.stats(g),(7,10));self.portable(g)

    def test_magma_silenced_source_has_no_future_commitment_trigger(self):
        g=self.game((TEST+'silence',TEST+'fire'),(MAGMA,));self.play(g,TEST+'silence',self.first(g,MAGMA).id)
        self.play(g,TEST+'fire');self.assertEqual(self.stats(g),(2,5))

    def test_magma_original_reference_does_not_buff_same_id_new_residence(self):
        g=self.game((TEST+'fire',),(TEST+'commit_wait',MAGMA));source=self.first(g,MAGMA).id
        presence=g.state.entities[source].board_presence_id;self.play(g,TEST+'fire');other=self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g,'bounce');self.choose(other,'bounce');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.first(g,MAGMA).id,source);self.assertNotEqual(g.state.entities[source].board_presence_id,presence)
        self.assertEqual(self.stats(g),(2,5));self.portable(g)

    def test_magma_original_reference_safely_skips_source_killed_by_earlier_reaction(self):
        g=self.game((TEST+'fire',),(TEST+'commit_wait',MAGMA));source=self.first(g,MAGMA).id
        self.play(g,TEST+'fire');self.choose(g,'kill');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertTrue(g.state.play_history[-1].completed);self.portable(g)

    def test_flock_real_public_objective_and_owner_next_start_before_draw(self):
        g=self.game((FLOCK,));source=self.play(g,FLOCK)
        self.assertFalse(self.entities(g,HATCHLING));effect,=g.state.players[1].player_effects
        self.assertEqual((effect.remaining_turns,self.r.player_effect(effect.spec_id).kind),(1,'objective'))
        for p in(1,2):
            view=g.for_player(p).observe()['observation'];row=next(x for x in view['players']if x['id']==1)
            self.assertEqual(row['player_effects'],[dict(effect_key=PREFIX+'flock',card_id=FLOCK,effect_kind='objective',remaining_turns=1)])
        self.portable(g);self.end(g);self.assertFalse(self.entities(g,HATCHLING));self.end(g)
        self.assertEqual([(e.attack,e.health)for e in self.entities(g,HATCHLING)],[(2,1)]*3)
        self.assertFalse(g.state.players[1].player_effects)
        events=[e for e in g.events if e.action==g.state.action_number and e.player_id==1]
        expiry=next(e.sequence for e in events if e.kind=='player_effect_expired')
        summons=[e.sequence for e in events if e.kind=='minion_summoned']
        draw=next(e.sequence for e in events if e.kind=='card_drawn')
        self.assertTrue(expiry<min(summons)<max(summons)<draw)
        self.assertTrue(all(x.request.cause.source.entity_id==source for x in g.state.card_summon_history))
        self.portable(g)

    def test_flock_full_shared_area_rejected_before_payment(self):
        g=self.game((FLOCK,)*6)
        for _ in range(5):self.play(g,FLOCK)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,FLOCK)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(len(g.state.players[1].player_effects),5)
        self.portable(g)

    def test_flock_duplicates_expire_independently_summoning_six(self):
        g=self.game((FLOCK,FLOCK));self.play(g,FLOCK);self.play(g,FLOCK);self.cycle(g)
        self.assertEqual(len(self.entities(g,HATCHLING)),6);self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(sum(e.kind=='player_effect_expired'for e in g.events),2);self.portable(g)

    def test_flock_full_and_partial_board_expire_with_only_actual_available_entries(self):
        for size,expected in((7,0),(6,1)):
            with self.subTest(size=size):
                g=self.game((FLOCK,),(YETI,)*size);self.play(g,FLOCK);self.cycle(g)
                self.assertEqual(len(self.entities(g,HATCHLING)),expected);self.assertFalse(g.state.players[1].player_effects)
                self.assertEqual(len(g.state.successful_summon_history),expected)

    def test_flock_shared_summon_quantity_applies_per_named_entry(self):
        g=self.game((FLOCK,),('CORE_DAL_575',));self.play(g,FLOCK);self.cycle(g)
        self.assertEqual(len(self.entities(g,HATCHLING)),6);self.portable(g)

    def test_flock_offturn_automatic_install_uses_recipient_first_real_start(self):
        g=self.game((TEST+'auto_flock',));self.play(g,TEST+'auto_flock')
        self.assertEqual(len(g.state.players[2].player_effects),1);self.end(g)
        self.assertEqual(len(self.entities(g,HATCHLING,2)),3);self.portable(g)

    def test_flock_skipped_opponent_slot_extra_owner_start_still_expires(self):
        g=self.game((FLOCK,TEST+'skip'));self.play(g,FLOCK);self.play(g,TEST+'skip');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(len(self.entities(g,HATCHLING)),3);self.portable(g)

    def test_flock_extra_scheduled_owner_turn_is_real_next_start(self):
        g=self.game((FLOCK,TEST+'extra'));self.play(g,FLOCK);self.play(g,TEST+'extra');self.end(g)
        self.assertEqual(g.state.active_player,1);self.assertEqual(len(self.entities(g,HATCHLING)),3)

    def test_flock_installed_during_start_does_not_consume_already_captured_boundary(self):
        g=self.game(board=(TEST+'late_flock',));self.cycle(g)
        self.assertEqual(len(g.state.players[1].player_effects),1);self.assertFalse(self.entities(g,HATCHLING))
        self.cycle(g);self.assertEqual(len(self.entities(g,HATCHLING)),3);self.portable(g)

    def test_flock_expiry_releases_slot_before_summon_wait_restores_replays_and_rolls_back(self):
        g=self.game((FLOCK,),(TEST+'hatch_wait',));self.play(g,FLOCK);self.cycle(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(len(self.entities(g,HATCHLING)),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.entities(g,HATCHLING)),3);self.portable(g)


if __name__=='__main__':unittest.main()
