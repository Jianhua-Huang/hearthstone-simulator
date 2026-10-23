"""Native historical conditions use actual damage, physical owners and held Dragons."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_conditional_battlecry_cards import (
    STUNNER,SLINGER,WHELP,DEPENDENCIES,load_batch,register_past_conditional_battlecry_cards)
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    Keyword,PlayCard,PlayerSetup,Rarity,Scenario,TriggerSpec,Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,GainArmor,
    GrantKeyword,Heal,InvokeBehavior,RequestChoice)
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.hero_health_targets import HeroDamageTakenTargetProfile,HeroHealthChangedTargetProfile
from hs_sim.engine.model import DamageKind,TribeChangeSpec
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.secrets import RemoveSecret
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference,MoveCard

P='k478.'
YETI='CS2_182';SECRET='EX1_287';BRANN='LOE_077'
DRAGON,DRAKE,ALL,NEUTRAL,UNKNOWN,WATCH=(P+x for x in ('dragon','drake','all','neutral','unknown','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=defaults();register_past_conditional_battlecry_cards(r);r._version='k478-'+mode
    for cid,cost,attack,health,tribes in ((DRAGON,2,2,5,('dragon',)),(DRAKE,8,8,8,('dragon',)),
            (ALL,3,3,3,('all',)),(NEUTRAL,4,4,6,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,
            metadata=replace(META,tribes=tribes)))
    r.register_card(CardDefinition(UNKNOWN,UNKNOWN,CardType.MINION,health=4,metadata=replace(META,tribes=None)))
    def hero(c):return c.state.players[c.player_id].hero_id
    def fail(c):raise ResolutionError('K478 deliberate late failure')
    def move_dragon(c):
        return tuple(MoveCard(CardReference.capture(c.state.entities[i]),c.player_id,Zone.DECK,
            position='top',source_id=c.source_id)for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id in (DRAGON,DRAKE))
    scripts={
        'hurt':lambda c:(Damage(hero(c),3,c.source_id),),
        'net_zero':lambda c:(Damage(hero(c),2,c.source_id),Heal(hero(c),2,c.source_id)),
        'armor_hit':lambda c:(GainArmor(c.player_id,5),Damage(hero(c),3,c.source_id)),
        'heal':lambda c:(Heal(hero(c),3,c.source_id),),
        'enemy_hit':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,4,c.source_id),),
        'prevented':lambda c:(GrantKeyword(hero(c),Keyword.IMMUNE,c.source_id),Damage(hero(c),3,c.source_id)),
        'zero':lambda c:(Damage(hero(c),0,c.source_id),),
        'control':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'make_dragon':lambda c:(ChangeMinionTribes(CardReference.capture(c.state.entities[
            next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==NEUTRAL)]),
            TribeChangeSpec('add',('dragon',)),c.source_id),),
        'indirect':lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),),
        'remove':lambda c:tuple(RemoveSecret(i)for i in c.state.players[c.player_id].secrets),
        'move_dragon':move_dragon,'fail':fail,
    }
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        if key!='fail':r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,
            requires_target=key in ('control','indirect'),metadata=META))
    def watch(c):
        e=c.event
        if mode=='wait' and e.kind=='minion_summoned' and c.state.entities[e.target_id].card_id in DEPENDENCIES:
            opts=tuple(ChoiceOption(key,key,()if key=='continue'else(InvokeBehavior(P+key,c.source_id,c.player_id),))
                for key in ('continue','fail','remove','hurt','move_dragon'))
            return (RequestChoice(c.player_id,opts,c.source_id),)
        if e.kind=='stored_card_buffed' and e.source_id is not None and c.state.entities[e.source_id].card_id==WHELP:
            if mode=='late_fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='after_reward':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,metadata=META,
        triggers=(TriggerSpec('minion_summoned',WATCH),TriggerSpec('stored_card_buffed',WATCH))))
    r.validate();return r


class PastConditionalBattlecryTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(YETI,),enemy_hand=(),mode='normal',active=1,seed=478):
        self.mode=mode
        if mode!='normal':board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(NEUTRAL,)*4,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(NEUTRAL,)*4,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),active_player=active,seed=seed),fixture(mode))

    def targets(self,g,cid):
        eid=self.entity(g,cid).id
        return {a.target_id for a in g.legal_actions()if isinstance(a,PlayCard)and a.entity_id==eid}

    def actions(self,g,cid):
        view=g.for_player(1).legal_actions()
        ref=next(x['ref']for x in view['observation']['players'][0]['hand']if x['card_id']==cid)
        return view,[x for x in view['actions']if x['type']=='play_card'and x['card']==ref]

    def test_complete_three_original_rows_and_six_primary_faces(self):
        data=load_batch();self.assertEqual(len(data['dependencies']),3);self.assertEqual(len(data['official_observations']),6)
        raw={r['record']['id']:r['record']for r in data['dependencies']}
        for face in data['official_observations']:
            self.assertEqual(batch.sha(face['response_file']),face['response_sha256'])
            batch.check_face(raw[face['card_id']],face['face'],face['locale'])
        r=fixture()
        self.assertEqual(r.card(SLINGER).metadata.tribes,('pirate',))
        self.assertEqual((r.card(WHELP).metadata.tribes,r.card(WHELP).metadata.subtypes),(('dragon',),('whelp',)))
        for cid in DEPENDENCIES:self.assertEqual(r.card(cid).cost,1);self.assertIsNotNone(r.card(cid).battlecry)

    def test_stunner_without_secret_is_targetless_and_rejects_arrow(self):
        g=self.game((STUNNER,));target=g.state.players[2].board[0]
        self.assertEqual(self.targets(g,STUNNER),{None});saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,STUNNER,target)
        self.assertEqual(g.snapshot(),saved);self.play(g,STUNNER)
        self.assertIn(target,g.state.players[2].board)

    def test_stunner_real_secret_returns_enemy_original_with_plus_two_price(self):
        g=self.game((SECRET,STUNNER));self.play(g,SECRET);target=g.state.players[2].board[0];before=g.state.players[1].mana
        self.assertIn(target,self.targets(g,STUNNER));self.play(g,STUNNER,target)
        self.assertIn(target,g.state.players[2].hand);self.assertEqual(g.state.entities[target].cost,6)
        self.assertEqual(g.state.players[1].mana,before-1);self.portable(g)

    def test_stunner_can_return_friendly_minion(self):
        g=self.game((SECRET,STUNNER),board=(NEUTRAL,));self.play(g,SECRET);target=g.state.players[1].board[0]
        self.play(g,STUNNER,target);self.assertIn(target,g.state.players[1].hand)
        self.assertEqual(g.state.entities[target].cost,6)

    def test_stolen_target_returns_to_physical_owner(self):
        g=self.game((SECRET,P+'control',STUNNER));target=g.state.players[2].board[0]
        self.play(g,SECRET);self.play(g,P+'control',target);self.play(g,STUNNER,target)
        self.assertIn(target,g.state.players[2].hand);self.assertEqual(g.state.entities[target].owner,2)

    def test_enemy_secret_does_not_enable_own_stunner(self):
        g=self.game((STUNNER,),enemy_hand=(SECRET,),active=2)
        self.play(g,SECRET,player=2);g.apply(EndTurn(2));self.assertTrue(g.state.players[2].secrets)
        self.assertEqual(self.targets(g,STUNNER),{None});self.play(g,STUNNER)

    def test_full_owner_hand_uses_ordinary_return_failure_death(self):
        g=self.game((SECRET,STUNNER),enemy_hand=(NEUTRAL,)*10);self.play(g,SECRET);target=g.state.players[2].board[0]
        self.play(g,STUNNER,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[2].hand),10)

    def test_stunner_repeat_does_not_recapture_returned_card(self):
        g=self.game((SECRET,STUNNER),board=(BRANN,));self.play(g,SECRET);target=g.state.players[2].board[0]
        self.play(g,STUNNER,target);self.assertEqual(g.state.entities[target].cost,6)
        self.assertEqual(g.state.players[2].hand.count(target),1)

    def test_secret_condition_rechecks_after_entry_wait(self):
        g=self.game((SECRET,STUNNER),mode='wait');self.play(g,SECRET);target=g.state.players[2].board[0]
        self.play(g,STUNNER,target);other=self.portable(g)
        self.choose(g,'remove');self.choose(other,'remove');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertIn(target,g.state.players[2].board)

    def test_slinger_no_damage_and_zero_damage_are_targetless(self):
        for prefix in (None,'zero','heal','enemy_hit','prevented'):
            with self.subTest(prefix=prefix):
                hand=(SLINGER,)if prefix is None else(P+prefix,SLINGER)
                g=self.game(hand)
                if prefix:self.play(g,P+prefix)
                self.assertEqual(self.targets(g,SLINGER),{None});self.play(g,SLINGER)

    def test_armor_damage_enables_target_even_without_health_loss(self):
        g=self.game((P+'armor_hit',SLINGER));self.play(g,P+'armor_hit');target=g.state.players[2].board[0]
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertEqual(self.targets(g,SLINGER),{target});self.play(g,SLINGER,target)
        self.assertEqual(g.state.entities[target].health,2);self.portable(g)

    def test_slinger_uses_received_damage_not_net_health_loss(self):
        g=self.game((P+'net_zero',P+'hurt',SLINGER));self.play(g,P+'net_zero');self.play(g,P+'hurt')
        target=g.state.players[2].board[0];self.play(g,SLINGER,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        rows=[d.health_result for d in g.state.damage_history if d.health_result.source_card_id==SLINGER]
        self.assertEqual(rows[0].damage_dealt,5)

    def test_previous_turn_damage_does_not_enable_slinger(self):
        g=self.game((P+'hurt',SLINGER));self.play(g,P+'hurt');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(self.targets(g,SLINGER),{None});self.play(g,SLINGER)

    def test_slinger_enemy_only_and_minion_damage_has_no_spell_bonus(self):
        g=self.game((P+'hurt',SLINGER),board=('EX1_012',));self.play(g,P+'hurt')
        target=g.state.players[2].board[0];self.assertEqual(self.targets(g,SLINGER),{target})
        self.play(g,SLINGER,target);self.assertEqual(g.state.entities[target].health,2)

    def test_slinger_player_commands_have_same_actual_armor_damage_gate(self):
        g=self.game((P+'armor_hit',SLINGER));_,before=self.actions(g,SLINGER)
        self.assertTrue(all(a['target']is None for a in before));self.play(g,P+'armor_hit')
        view,actions=self.actions(g,SLINGER);self.assertTrue(actions);self.assertTrue(all(a['target']is not None for a in actions))
        self.assertTrue(g.for_player(1).submit(dict(revision=view['revision'],action=actions[0]))['accepted'])

    def test_new_damage_while_waiting_does_not_invent_unsubmitted_target(self):
        g=self.game((SLINGER,),mode='wait');self.play(g,SLINGER);other=self.portable(g)
        self.choose(g,'hurt');self.choose(other,'hurt');self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,5)

    def test_paid_slinger_wait_failure_rolls_back_exact_wait(self):
        g=self.game((P+'hurt',SLINGER),mode='wait');self.play(g,P+'hurt')
        self.play(g,SLINGER,g.state.players[2].board[0]);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(g.state.players[1].mana,39)

    def test_damage_profile_is_distinct_finite_and_preserves_old_health_basis(self):
        a=defaults();b=defaults();register_past_conditional_battlecry_cards(a);register_past_conditional_battlecry_cards(b)
        a._version=b._version='k478-same-profile-version'
        b._hero_health_target_profiles.pop(SLINGER);b.register_hero_health_target_profile(HeroHealthChangedTargetProfile(SLINGER))
        self.assertNotEqual(a.fingerprint(),b.fingerprint())
        with self.assertRaises(ValueError):HeroDamageTakenTargetProfile(SLINGER,'missing_health')
        with self.assertRaises(ValueError):a.register_hero_health_target_profile(HeroDamageTakenTargetProfile(STUNNER))
        self.assertEqual(a.hero_health_target_profiles[SLINGER].condition,'actual_received_damage_current_turn')

    def test_whelp_without_other_held_dragon_is_plain_and_consumes_no_rng(self):
        g=self.game((WHELP,NEUTRAL));rng=g.snapshot()['rng_state'];source=self.play(g,WHELP)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,1))
        self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_one_held_dragon_and_source_both_gain_one_without_rng(self):
        g=self.game((WHELP,DRAGON));target=self.entity(g,DRAGON).id;rng=g.snapshot()['rng_state'];source=self.play(g,WHELP)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(3,6))
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,2))
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_multiple_physical_dragons_randomly_buff_exactly_one_without_discover(self):
        g=self.game((WHELP,DRAGON,DRAGON,DRAKE));ids=g.state.players[1].hand[1:];rng=g.snapshot()['rng_state'];source=self.play(g,WHELP)
        changes=[g.state.entities[i].attack-(8 if g.state.entities[i].card_id==DRAKE else 2)for i in ids]
        self.assertEqual(sorted(changes),[0,0,1]);self.assertNotEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(g.state.entities[source].attack,3);self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.card_discovery_history);self.portable(g)

    def test_current_added_dragon_type_and_all_type_match(self):
        for held,prefix in ((ALL,None),(NEUTRAL,P+'make_dragon')):
            with self.subTest(held=held):
                g=self.game((WHELP,held)if prefix is None else(prefix,WHELP,held))
                if prefix:self.play(g,prefix)
                source=self.play(g,WHELP);self.assertEqual(g.state.entities[source].attack,3)

    def test_unknown_later_hand_type_is_not_silently_filtered(self):
        g=self.game((WHELP,DRAGON,UNKNOWN));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,WHELP)
        self.assertEqual(g.snapshot(),saved)

    def test_whelp_rechecks_hand_after_entry_wait(self):
        g=self.game((WHELP,DRAGON),mode='wait');source=self.play(g,WHELP);self.choose(g,'move_dragon')
        self.assertEqual(g.state.entities[source].attack,2)

    def test_wait_between_held_and_self_buff_restores_original_continuation(self):
        g=self.game((WHELP,DRAGON),mode='after_reward');source=self.play(g,WHELP)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[source].attack,3)

    def test_whelp_late_failure_rolls_back_hand_buff_source_mana_and_rng(self):
        g=self.game((WHELP,DRAGON,DRAKE),mode='late_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,WHELP)
        self.assertEqual(g.snapshot(),saved)

    def test_repeated_whelp_reaccepts_rewards_without_extra_payment(self):
        g=self.game((WHELP,DRAGON),board=(BRANN,));target=self.entity(g,DRAGON).id;source=self.play(g,WHELP)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[source].attack,g.state.players[1].mana),(4,4,39))

    def test_ordinary_summon_is_not_a_battlecry(self):
        from hs_sim.engine.effects import Summon
        r=fixture('summon');r.register_behavior(P+'summon',lambda c:(Summon(c.player_id,WHELP),))
        r.register_card(CardDefinition(P+'summon','Summon',CardType.SPELL,on_play=P+'summon',metadata=META))
        self.mode='summon'
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(P+'summon',DRAGON),mana=5,max_mana=5),PlayerSetup('HERO_08'))),r)
        target=self.entity(g,DRAGON).id;self.play(g,P+'summon')
        self.assertEqual(g.state.entities[target].attack,2)

    def test_opponent_does_not_learn_randomly_buffed_held_card(self):
        g=self.game((WHELP,DRAGON,DRAKE));self.play(g,WHELP)
        visible=json.dumps(g.for_player(2).observe())+json.dumps(g.for_player(2).events())
        self.assertNotIn(DRAGON,visible);self.assertNotIn(DRAKE,visible)
        self.assertNotIn('damage_history',visible);self.assertNotIn('before_state',visible)

    def test_old_snapshot_schema_rejected(self):
        g=self.game();saved=g.snapshot();saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture())
