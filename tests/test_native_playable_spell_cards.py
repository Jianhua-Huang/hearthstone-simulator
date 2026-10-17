"""Actual shared admission, isolated previews and original Temporary draws."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.native_playable_spell_cards import FORGER, POOL_ID, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, PaymentType, PlayCard, PlayerSetup, PlayerTargetRuleSpec, Rarity, Ruleset,
    Scenario, SelectChoice, SnapshotError, TargetSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CostSpec,
    GainArmor, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.generated_card_preview import can_receive_and_play
from hs_sim.engine.model import LimitedTriggerSpec, PlayerEffectSpec, SecretSpec, Keyword, RewindSpec
from hs_sim.engine.playable_spell_generation import DRAW, GeneratePlayableTemporarySpell, decode
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash

P = 'k146.'
CHEAP, BIG, ENEMY, WEAPON, PLAYER, SECRET, ONGOING, UNKNOWN, FILL = (
    P+n for n in ('cheap', 'big', 'enemy', 'weapon_required', 'player_rule', 'secret', 'ongoing', 'unknown', 'filler'))
MEMBERS = (CHEAP, BIG, ENEMY, WEAPON, PLAYER)
CONTEXT = GenerationContext('k146-complete-explicit-playable-spell-pool', 'experimental')


def registry(mode=None, members=MEMBERS):
    r = build_registry()
    r.register_behavior(P+'marker', lambda c: (GainArmor(c.player_id, 1),))
    r.register_behavior(P+'noop', lambda c: ())
    def player_rule(c):
        if 'rng_state' in c.observation or 'entity_id' in c.source:
            raise AssertionError('Preview player predicate received private state')
        return c.target is not None and c.source['card_id'] == PLAYER
    r.register_player_target_rule(PlayerTargetRuleSpec(P+'visible', 'v1'), player_rule)
    meta = CardMetadata(True, (CardClass.MAGE,), Rarity.COMMON, tribes=())
    for cid, cost, kwargs in ((CHEAP, 0, {}), (BIG, 10, {}),
            (ENEMY, 1, {'targeting':TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy')}),
            (WEAPON, 1, {'requires_weapon':True}),
            (PLAYER, 1, {'target_rule':P+'visible', 'targeting':TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly')})):
        c = CardDefinition(cid, cid, CardType.SPELL, cost=cost, metadata=meta, on_play=P+'marker', **kwargs)
        r.register_card(c); r.register_pool_card(PoolCard.from_definition(c))
    r.register_secret_condition(P+'never', lambda c: False)
    secret = CardDefinition(SECRET, SECRET, CardType.SPELL, cost=1, metadata=meta,
        keywords=(Keyword.SECRET,),
        secret=SecretSpec(P+'secret_key', ('turn_ended',), P+'never', P+'noop'))
    r.register_card(secret); r.register_pool_card(PoolCard.from_definition(secret))
    r.register_player_effect(PlayerEffectSpec(P+'ongoing', ONGOING, kind='objective', duration=3, tick_event='turn_ended'))
    ongoing = CardDefinition(ONGOING, ONGOING, CardType.SPELL, cost=0, metadata=meta,
        ongoing_effect_id=P+'ongoing')
    r.register_card(ongoing); r.register_pool_card(PoolCard.from_definition(ongoing))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, cost=1, attack=1, health=3,
        metadata=CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())))
    r.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, 1, meta,
        battlecry=False, deathrattle=False, choose_one=False))
    r.register_pool(PoolDefinition(POOL_ID, 'k146-explicit-v1', CONTEXT.target_id, CONTEXT.mode,
        tuple(PoolMember(cid, 3 if cid == CHEAP else 1) for cid in members), complete=True))
    def request(c):
        return GeneratePlayableTemporarySpell(c.player_id, c.source_id, POOL_ID)
    def fail(c):
        raise ResolutionError('K146 deliberate acquisition failure')
    bodies = {
        'discount':lambda c:(AddCostModifier(c.player_id, CostSpec(delta=-10, card_types=(CardType.SPELL,)),
            uses_remaining=1, source_id=c.source_id, temporary_only=True),),
        'health':lambda c:(AddCostModifier(c.player_id, CostSpec(card_types=(CardType.SPELL,), payment=PaymentType.HEALTH),
            uses_remaining=1, source_id=c.source_id),),
        'generate':lambda c:(request(c),),
        'wait':lambda c:(RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Generate', (request(c),)),
            ChoiceOption('bad', 'Fail after generation', (request(c), InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),),
        'rewind':lambda c:(request(c),),
        'for_player2':lambda c:(GeneratePlayableTemporarySpell(2, c.source_id, POOL_ID),),
        'fail':fail}
    for key, body in bodies.items():
        r.register_behavior(P+key, body)
        if key != 'fail':
            kwargs = {'keywords':(Keyword.REWIND,), 'rewind':RewindSpec()} if key == 'rewind' else {}
            r.register_card(CardDefinition(P+key, P+key, CardType.SPELL, on_play=P+key, **kwargs))
    if mode in ('fail', 'full'):
        def eligible(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.card_id == FORGER and c.event.player_id == c.player_id
        def watch(c):
            if mode == 'fail':return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            return (AddToHand(c.player_id, FILL, c.source_id),)
        r.register_behavior(P+'watch', watch); r.register_trigger_condition(P+'eligible', eligible)
        event = 'card_created' if mode == 'fail' else 'card_committed'
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.WEAPON, attack=1, durability=4,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', P+'eligible'),)))
    elif mode == 'weapon':
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.WEAPON, attack=1, durability=4))
    r.validate()
    return r


@lru_cache(maxsize=None)
def shared(mode, members):
    return registry(mode, members)


def rehash(s):
    s['events_hash'] = canonical_hash(s['events'])
    s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class NativePlayableSpellTests(unittest.TestCase):
    def game(self, hand=(FORGER,), *, members=MEMBERS, mode=None, enemy=(), rules=None, board=()):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board,
            deck=(FILL,)*6, mana=10, max_mana=10, weapon_card_id=P+'watch' if mode else None),
            PlayerSetup('HERO_09', hand=(FORGER,), board=enemy, deck=(FILL,)*6, mana=10, max_mana=10)),
            seed=146, generation_context=CONTEXT), shared(*self.config), ruleset=rules or Ruleset())
    def play(self, g, cid, player=1, target=None):
        source = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, source, target_id=target,
            position=len(g.state.players[player].board) if g.state.entities[source].kind == CardType.MINION else None))
        return source
    def draws(self, g):return [decode(g,e) for e in g.events if e.kind == DRAW]
    def choose(self, g, key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def same(self, g, saved):self.assertEqual(canonical_hash(g.snapshot()), canonical_hash(saved))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        self.same(Game.from_snapshot(saved,registry(*self.config)),saved)
        self.same(g.clone(),saved);self.same(replay(build_replay(g),registry(*self.config)),saved)
        for actor in (1,2):
            public=json.dumps(g.for_player(actor).observe())+json.dumps(g.player_events(actor))
            for key in ('information_json','rng_before','rng_after','candidates','playable'):
                self.assertNotIn('"'+key+'"',public)
            self.assertNotIn('PlayableSpellDraw',public)

    def test_complete_source_two_primary_faces_and_actual_neutral_native_body(self):
        from tools.card_batch import check_face
        d=load_batch();row,=d['cards'];self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:check_face(row['record'],o['face'],o['locale'])
        c=shared(None,MEMBERS).card(FORGER)
        self.assertEqual((c.cost,c.attack,c.health,c.metadata.classes),(2,2,2,(CardClass.NEUTRAL,)))
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_native_paid_generation_uses_targets_weapon_price_and_private_player_predicate(self):
        g=self.game();before=g.state;source=self.play(g,FORGER);draw,=self.draws(g)
        self.assertEqual(draw.candidates,tuple(sorted(((CHEAP,3),(BIG,1),(ENEMY,1),(WEAPON,1),(PLAYER,1)))))
        self.assertEqual(draw.playable,tuple(sorted(((CHEAP,3),(PLAYER,1)))))
        self.assertEqual((g.state.players[1].mana,len(g.state.hand_entries)),(8,len(before.hand_entries)+1))
        e=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual((e.card_id,e.origin_entity_id,e.hand_lifetime.expires_turn),(draw.selected[0],source,g.state.turn))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.portable(g)

    def test_enemy_presence_and_equipment_admission_are_actual_not_mana_only(self):
        for mode,enemy,allowed in ((None,(),()),(None,(FILL,),((ENEMY,1),)),('weapon',(),((WEAPON,1),))):
            with self.subTest(mode=mode,enemy=enemy):
                g=self.game(members=(ENEMY,WEAPON),mode=mode,enemy=enemy);self.play(g,FORGER)
                self.assertEqual(self.draws(g)[0].playable,allowed)

    def test_temporary_only_limited_discount_is_quoted_but_consumed_only_by_actual_play(self):
        g=self.game((P+'discount',FORGER),members=(BIG,));self.play(g,P+'discount');self.play(g,FORGER)
        self.assertEqual(self.draws(g)[0].playable,((BIG,1),))
        self.assertEqual(g.state.players[1].cost_modifiers[-1].uses_remaining,1)
        mana=g.state.players[1].mana;self.play(g,BIG)
        self.assertEqual(g.state.players[1].mana,mana)
        self.assertFalse(any(m.uses_remaining==1 for m in g.state.players[1].cost_modifiers))

    def test_health_payment_can_admit_spell_above_remaining_mana_without_prepayment(self):
        g=self.game((P+'health',FORGER),members=(BIG,));self.play(g,P+'health');self.play(g,FORGER)
        hero=g.state.players[1].hero_id
        self.assertEqual((g.state.entities[hero].health,g.state.players[1].mana),(30,8))
        self.assertEqual(self.draws(g)[0].selected,(BIG,));self.play(g,BIG)
        self.assertEqual((g.state.entities[hero].health,g.state.players[1].mana),(20,8))

    def test_duplicate_secret_and_ongoing_area_limits_are_shared_with_real_admission(self):
        for cid,rules in ((SECRET,None),(ONGOING,Ruleset(max_ongoing_effects=1))):
            with self.subTest(card=cid):
                g=self.game((cid,FORGER),members=(cid,),rules=rules);self.play(g,cid)
                before=g.snapshot()['rng_state'];self.play(g,FORGER)
                draw,=self.draws(g);self.assertEqual((draw.playable,draw.selected),((),()))
                self.assertEqual(g.snapshot()['rng_state'],before)

    def test_existing_choose_one_spell_qualifies_via_an_actual_legal_branch(self):
        cid='CORE_EX1_160';g=self.game(members=(cid,));self.play(g,FORGER)
        self.assertEqual(self.draws(g)[0].selected,(cid,));self.portable(g)

    def test_preview_isolated_materialization_does_not_use_game_actions_or_rng(self):
        g=self.game();saved=g.snapshot();source=g.state.players[1].hand[0];state=g.state
        with patch.object(Game,'apply',side_effect=AssertionError('Preview tried an action')),patch.object(random.Random,'randrange',side_effect=AssertionError('Preview used RNG')):
            self.assertTrue(can_receive_and_play(state,g.registry,g.ruleset,g._information,1,CHEAP,source,state.turn))
            self.assertFalse(can_receive_and_play(state,g.registry,g.ruleset,g._information,1,ENEMY,source,state.turn))
        self.same(g,saved)

    def test_unknown_independent_eligible_spell_fails_before_any_rng_and_rolls_back(self):
        g=self.game(members=(CHEAP,UNKNOWN));saved=g.snapshot();calls=[]
        def fail(*args,**kwargs):calls.append(args);raise AssertionError('Unknown candidate reached RNG')
        with patch.object(random.Random,'randrange',fail),self.assertRaises((ResolutionError,ValueError)):
            self.play(g,FORGER)
        self.assertFalse(calls);self.same(g,saved)

    def test_empty_admitted_pool_retains_original_broad_inventory_without_rng(self):
        g=self.game(members=(ENEMY,BIG));before=g.snapshot()['rng_state'];self.play(g,FORGER);draw,=self.draws(g)
        self.assertEqual(draw.playable,());self.assertEqual(len(draw.candidates),2)
        self.assertEqual((draw.rng_before,draw.selected),(draw.rng_after,()))
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_actual_temporary_expiry_and_full_hand_burn_use_existing_delivery(self):
        g=self.game(members=(CHEAP,));self.play(g,FORGER);eid=g.state.players[1].hand[0]
        g.apply(EndTurn(1));self.assertNotIn(eid,g.state.players[1].hand)
        g=self.game(members=(CHEAP,),mode='full',rules=Ruleset(max_hand=1));source=self.play(g,FORGER)
        self.assertEqual(self.draws(g)[0].selected,(CHEAP,))
        self.assertTrue(any(e.kind=='card_burned'and e.source_id==source for e in g.events))

    def test_waiting_request_restores_and_failed_continuation_rolls_back_local_generation(self):
        g=self.game((P+'wait',),members=(CHEAP,));self.play(g,P+'wait');self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.same(g,saved);self.choose(g,'ok');self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_acquisition_failure_rolls_back_source_payment_preview_and_rng(self):
        g=self.game(members=(CHEAP,),mode='fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,FORGER)
        self.same(g,saved)

    def test_actual_rewind_preserves_diagnostic_qualification_but_replaces_created_card(self):
        g=self.game((P+'rewind',),members=(CHEAP,));self.play(g,P+'rewind');old=set(g.state.players[1].hand)
        self.choose(g,'retry');self.assertEqual(len(self.draws(g)),2)
        self.assertFalse(old&set(g.state.players[1].hand));self.portable(g)

    def test_second_recipient_is_qualified_with_own_resources_without_faking_active_turn(self):
        g=self.game((P+'for_player2',),members=(CHEAP,));self.play(g,P+'for_player2');draw,=self.draws(g)
        self.assertEqual((draw.request.player_id,draw.before.state.active_player),(2,1))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand],[FORGER,CHEAP])
        self.portable(g)

    def test_rehashed_admission_crop_wrong_context_and_old_schema_are_rejected(self):
        g=self.game(members=(CHEAP,BIG));self.play(g,FORGER);saved=g.snapshot()
        index=next(i for i,e in enumerate(g.events)if e.kind==DRAW)
        for case in ('crop','context','version','schema'):
            with self.subTest(case=case):
                other=deepcopy(saved)
                if case=='schema':other['schema_version']=352
                else:
                    fields=other['events'][index]['data']['draw']['fields']
                    if case=='crop':fields['candidates']={'tuple':[]};fields['playable']={'tuple':[]};fields['selected']={'tuple':[]};fields['rng_after']=deepcopy(fields['rng_before'])
                    elif case=='context':fields['before']['fields']['player_id']=2
                    else:fields['pool_version']+='.changed'
                with self.assertRaises((SnapshotError,ValueError,ResolutionError)):
                    Game.from_snapshot(rehash(other),registry(*self.config))


if __name__=='__main__':unittest.main()
