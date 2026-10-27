"""Both new native cards enter through the complete, untrimmed27-member reference."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import paladin_mech_source_continuations as native
from hs_sim.cards.simple_followup_p89_cards import QUERIES
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, Game, IllegalAction,
    Keyword, LaunchStarship, PlayerSetup, ResolutionError, Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.dredge import SelectDredgedCardWithSourceStats
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, CopyMinion, Damage, Destroy, Draw,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.hand_upgrades import SetStoredMinionStats
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k587.'
SOURCE, PIECE, POOL = 'TIME_016','SC_405','constructed.past.cards'
CONTEXT = GenerationContext(P+'complete-27-reference-native-validation','experimental')
UNIT, SECOND, OTHER, WATCH, KILL, BOUNCE, QUIET, COPY, REPEAT, DRAW, SET_HELD, MAKE, DECK_MAKE, HURT = (
    P+x for x in ('unit','second','spell','watch','kill','bounce','silence','copy','repeat','draw','set-held','make','deck-make','hurt'))
META = CardMetadata(False,(CardClass.PALADIN,),None)


@lru_cache(None)
def host(mode='normal', role='writer'):
    f=build_cn37_local_pool_format(); r=f.registry; ref=batch.read('data/cards/past-paladin-mech-local-reference-v1.json')
    # Explicit reference target; the production host's source scope remains
    # separately controlled until the full union binding is reviewed.
    for cid in ref['candidate_ids']:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_pool(PoolDefinition(POOL,P+'complete-original-reference',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid) for cid in ref['candidate_ids']),complete=True))
    for cid,attack,health in ((UNIT,1,3),(SECOND,2,4)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,metadata=META))
    r.register_card(CardDefinition(OTHER,OTHER,CardType.SPELL,metadata=META))
    def fail(c):raise ResolutionError('K587 deliberate native continuation failure')
    def back(c):
        e=c.state.entities[c.target_id]
        return (MoveCard(CardReference.capture(e),c.player_id,Zone.DECK,source_id=c.source_id),)
    def watch(c):
        e=c.event
        if e.player_id!=c.player_id:return ()
        if e.kind=='card_dredged':
            if mode=='source-kill':
                parent=next(c.state.entities[i] for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==native.SAVIOR)
                return (Buff(parent.id,8,8,c.source_id),Destroy(parent.id,c.source_id))
            if mode=='reenter':
                target=c.state.entities[e.target_id]
                return (MoveCard(CardReference.capture(target),c.player_id,Zone.HAND,source_id=c.source_id),
                    InvokeBehavior(P+'back',c.source_id,c.player_id,target_id=target.id))
            if mode=='dredge-wait':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fault','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if e.kind=='stored_card_transformed' and dict(e.data).get('old_card_id')==native.HELLION:
            if mode=='launch-fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            hand_forms=[i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==native.HELLBAT]
            if mode=='launch-wait' and hand_forms and e.target_id==min(hand_forms):
                return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                    ChoiceOption('fault','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'fail',fail);r.register_behavior(P+'back',back);r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=META,
        triggers=tuple(TriggerSpec(k,WATCH) for k in ('card_dredged','stored_card_transformed'))))
    def set_held(c):
        e=next(c.state.entities[i] for i in reversed(c.state.players[c.player_id].hand) if c.state.entities[i].card_id==native.HELLION)
        from hs_sim.engine.model import CostSpec
        return (SetStoredMinionStats(CardReference.capture(e),2,3,c.source_id,CostSpec(set_to=0)),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        QUIET:lambda c:(Silence(c.target_id),),COPY:lambda c:(CopyMinion(c.target_id,c.player_id),),
        REPEAT:lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id,choices='player'),),
        DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),SET_HELD:set_held,
        MAKE:lambda c:(AddToHand(c.player_id,native.HELLION,c.source_id),),
        DECK_MAKE:lambda c:(AddToDeck(c.player_id,native.HELLION,'bottom',c.source_id),),
        HURT:lambda c:(Damage(c.target_id,2,c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            requires_target=cid in (KILL,BOUNCE,QUIET,COPY,REPEAT,HURT)))
    r.validate();return f


def seed_for(cid):
    rows=resolve_candidates(host().registry,CONTEXT,POOL,QUERIES[SOURCE],source_card_id=SOURCE)
    return next(n for n in range(1000) if cid in sample_candidates(Random(n),rows,3,replacement=False))


class PaladinMechSourceContinuationTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:host(mode,role).registry)
    mode='normal'

    def game(self,desired=native.SAVIOR,*,hand=(),deck=(UNIT,SECOND,OTHER),own=(),enemy=(),player=1,mode='normal'):
        self.mode=mode
        if mode!='normal':own=(WATCH,*own)
        players=tuple(PlayerSetup('HERO_04',hand=(SOURCE,*hand) if p==player else (),board=own if p==player else enemy,
            deck=deck if p==player else (),mana=60,max_mana=60,mana_cap=60) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed_for(desired),
            generation_context=CONTEXT),host(mode).registry)

    def acquire(self,g,cid,player=1):
        self.play(g,SOURCE,player=player); q=g.state.pending_choice
        before=set(g.state.players[player].hand)
        self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        created=set(g.state.players[player].hand)-before;self.assertEqual(len(created),1)
        return g.state.entities[created.pop()]

    def dredge_pick(self,g,cid):
        self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id==cid))

    def launch(self,g,player=1):
        piece=self.play(g,PIECE,player=player);self.play(g,KILL,piece,player=player)
        ship=construction(g.state,player);self.assertIsNotNone(ship)
        g.apply(LaunchStarship(player,ship.id));return ship.id

    def test_full_original_reference_complete_main_faces_and_unchanged_named_form(self):
        data=native.load_batch();ref=batch.read(data['reference_document']);self.assertEqual(len(ref['candidate_ids']),27)
        self.assertEqual(len(resolve_candidates(host().registry,CONTEXT,POOL,QUERIES[SOURCE],source_card_id=SOURCE)),27)
        rows={v['record']['id']:v['record'] for v in data['dependencies']}
        for face in data['official_observations']:batch.check_face(rows[face['card_id']],face['face'],face['locale'])
        self.assertEqual(data['evidence_only'][0]['record']['id'],'TSC_083e')
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_savior_full_source_plus_five_then_original_dredge_adds_current_attack_and_health_in_both_seats(self):
        for p in (1,2):
            g=self.game(player=p);e=self.acquire(g,native.SAVIOR,p);self.assertEqual((e.attack,e.max_health),(7,7))
            self.play(g,native.SAVIOR,player=p);self.assertEqual(g.state.play_history[-1].cost,2)
            before={i:g.state.entities[i].zone_epoch for i in g.state.players[p].deck}
            self.dredge_pick(g,UNIT);target=g.state.entities[g.state.players[p].deck[0]]
            self.assertEqual(target.card_id,UNIT);self.assertEqual((target.attack,target.max_health),(8,10))
            self.assertEqual(target.zone_epoch,before[target.id]+1);self.assertEqual(g.state.draw_history,[])
        self.portable(g)

    def test_savior_aura_attack_and_damaged_remaining_health_are_captured_for_each_actual_battlecry(self):
        g=self.game(hand=(REPEAT,HURT),own=(native.HELLION,));self.acquire(g,native.SAVIOR);root=self.play(g,native.SAVIOR)
        self.dredge_pick(g,OTHER)
        self.play(g,HURT,root);self.assertEqual(g.state.entities[root].health,5)
        self.assertEqual(g.state.entities[root].attack,8)
        self.play(g,REPEAT,root);self.dredge_pick(g,UNIT)
        target=g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual((target.attack,target.max_health),(9,8))

    def test_savior_spell_selection_and_empty_deck_never_invent_a_stat_reward_or_rng(self):
        g=self.game();self.acquire(g,native.SAVIOR);self.play(g,native.SAVIOR);self.dredge_pick(g,OTHER)
        target=g.state.entities[g.state.players[1].deck[0]];self.assertEqual(target.card_id,OTHER);self.assertEqual(target.enchantments,[])
        g=self.game(deck=());self.acquire(g,native.SAVIOR);rng=g._rng.getstate();self.play(g,native.SAVIOR)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng)

    def test_savior_pending_dredge_restores_original_context_clone_replay_and_invalid_selection_is_atomic(self):
        g=self.game();self.acquire(g,native.SAVIOR);self.play(g,native.SAVIOR);before=g.snapshot();restored=self.portable(g)
        with self.assertRaises(IllegalAction):self.choose(g,'not-a-real-dredge-option')
        self.assertEqual(g.snapshot(),before)
        for current in (g,restored):self.dredge_pick(current,SECOND)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_savior_source_growth_and_death_after_selection_do_not_rewrite_original_stat_packet(self):
        g=self.game(mode='source-kill');self.acquire(g,native.SAVIOR);self.play(g,native.SAVIOR)
        self.dredge_pick(g,UNIT);target=g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual((target.attack,target.max_health),(8,10))
        self.assertFalse(any(g.state.entities[i].card_id==native.SAVIOR for i in g.state.players[1].board))

    def test_savior_dredged_same_entity_leaves_and_reenters_deck_without_borrowing_old_reward(self):
        g=self.game(mode='reenter');self.acquire(g,native.SAVIOR);self.play(g,native.SAVIOR)
        target=next(g.state.entities[i] for i in g.state.players[1].deck if g.state.entities[i].card_id==UNIT)
        self.dredge_pick(g,UNIT);self.assertEqual((g.state.entities[target.id].attack,g.state.entities[target.id].max_health),(1,3))

    def test_savior_reorder_notification_wait_keeps_selected_residence_and_failure_rolls_back(self):
        g=self.game(mode='dredge-wait');self.acquire(g,native.SAVIOR);self.play(g,native.SAVIOR);self.dredge_pick(g,UNIT)
        before=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for current in (g,restored):self.choose(current)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_hellion_before_launch_gives_only_other_minions_one_attack(self):
        g=self.game(native.HELLION,own=(UNIT,));e=self.acquire(g,native.HELLION);self.assertEqual((e.attack,e.max_health),(9,9))
        root=self.play(g,native.HELLION);ally=self.entity(g,UNIT,zone='board')
        self.assertEqual(ally.attack,2);self.assertNotIn(Keyword.RUSH,ally.keywords);self.assertEqual(g.state.entities[root].attack,9)

    def test_actual_piece_launch_upgrades_hand_and_deck_preserving_set_stats_and_cost_then_real_aura_combat(self):
        g=self.game(native.HELLION,hand=(PIECE,KILL,SET_HELD,UNIT),deck=(native.HELLION,SECOND),enemy=(UNIT,))
        e=self.acquire(g,native.HELLION);eid=e.id;self.play(g,SET_HELD);self.launch(g)
        e=g.state.entities[eid];self.assertEqual(e.card_id,native.HELLBAT);self.assertEqual((e.attack,e.max_health),(2,3))
        from hs_sim.engine.costs import quote_unselected_cost
        self.assertEqual(quote_unselected_cost(g.state,g.registry,e).amount,0)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[native.HELLBAT,SECOND])
        from hs_sim.engine import PlayCard
        g.apply(PlayCard(1,eid));ally=self.play(g,UNIT);target=self.entity(g,UNIT,2,'board').id
        self.assertEqual(g.state.entities[ally].attack,3);self.assertIn(Keyword.RUSH,g.state.entities[ally].keywords)
        g.apply(Attack(1,ally,target));self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.portable(g)

    def test_existing_board_hellion_stays_original_when_launch_occurs_then_bounce_uses_stored_form(self):
        g=self.game(native.HELLION,hand=(PIECE,KILL,BOUNCE),own=(UNIT,));self.acquire(g,native.HELLION);root=self.play(g,native.HELLION)
        self.launch(g);self.assertEqual(g.state.entities[root].card_id,native.HELLION)
        self.assertEqual(self.entity(g,UNIT,zone='board').attack,2)
        self.play(g,BOUNCE,root);self.assertEqual(g.state.entities[root].card_id,native.HELLBAT)

    def test_later_full_source_discovery_and_new_hand_deck_cards_upgrade_from_original_launch_history(self):
        for p in (1,2):
            g=self.game(native.HELLION,hand=(PIECE,KILL,MAKE,DECK_MAKE),player=p)
            self.launch(g,p);e=self.acquire(g,native.HELLION,p)
            self.assertEqual((e.card_id,e.attack,e.max_health),(native.HELLBAT,9,9))
            self.play(g,MAKE,player=p);self.play(g,DECK_MAKE,player=p)
            self.assertFalse(any(g.state.entities[i].card_id==native.HELLION for z in ('hand','deck') for i in getattr(g.state.players[p],z)))

    def test_first_launch_form_notification_has_entire_group_and_wait_restores_without_relaunch(self):
        g=self.game(native.HELLION,hand=(native.HELLION,PIECE,KILL),deck=(native.HELLION,),mode='launch-wait')
        self.launch(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(any(g.state.entities[i].card_id==native.HELLION for z in ('hand','deck') for i in getattr(g.state.players[1],z)))
        before=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
        for current in (g,restored):self.choose(current)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(len(g.state.starship_history),1)

    def test_launch_form_observer_failure_rolls_back_launch_payment_history_all_faces_and_rng(self):
        g=self.game(native.HELLION,hand=(native.HELLION,PIECE,KILL),deck=(native.HELLION,),mode='launch-fail')
        piece=self.play(g,PIECE);self.play(g,KILL,piece);ship=construction(g.state,1);before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(LaunchStarship(1,ship.id))
        self.assertEqual(g.snapshot(),before)

    def test_rehashed_dredge_original_source_or_mixed_request_is_rejected(self):
        g=self.game();self.acquire(g,native.SAVIOR);self.play(g,native.SAVIOR);saved=g.snapshot()
        def alter(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('DredgeWithSourceStats'):
                    value['fields']['original']['fields']['player_id']=2;return True
                return any(alter(v) for v in value.values())
            if isinstance(value,list):return any(alter(v) for v in value)
            return False
        effect=g._frame.options[0].effects[0];self.assertIs(type(effect),SelectDredgedCardWithSourceStats)
        with self.assertRaises(ValueError):replace(effect,spec=replace(effect.spec,player_id=2))
        self.assertTrue(alter(saved))
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,host('normal','independent-reader').registry)
        self.portable(g)

    def test_player_views_never_reveal_other_deck_forms_or_internal_dredge_context(self):
        g=self.game(native.HELLION,hand=(native.HELLION,PIECE,KILL),deck=(native.HELLION,));self.launch(g)
        enemy=json.dumps(g.observe(2));self.assertNotIn(native.HELLION,enemy);self.assertNotIn(native.HELLBAT,enemy)
        g=self.game();self.acquire(g,native.SAVIOR);self.play(g,native.SAVIOR)
        for p in (1,2):
            view=json.dumps(g.observe(p))
            for word in ('rng_state','original','request','battlecry_history','resolution_frame','stored_launch_form_profiles'):
                self.assertNotIn('"'+word+'"',view)

    def test_changed_complete_hellbat_dependency_is_rejected_before_partial_card_registration(self):
        r=build_registry()
        for cid in native.LEAVES:r._cards.pop(cid);r._pool_cards.pop(cid)
        r._stored_launch_form_profiles.clear();r._cards[native.HELLBAT]=replace(r.card(native.HELLBAT),health=5)
        before=(dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with self.assertRaises(TargetValidationError):native.register_paladin_mech_source_continuations(r)
        self.assertEqual((dict(r.cards),dict(r.pool_cards),dict(r._behaviors)),before)


if __name__=='__main__':unittest.main()
