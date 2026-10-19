"""Native hero damage replacement and bounded physical generation."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards.native_blight_replacement_cards import CARD,BLIGHT,load_batch
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.blight_damage_replacement import RULE
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.deck_generation import ShuffleGeneratedCopies
from hs_sim.engine.effects import (ChoiceOption,ChangeControl,Damage,DamageBatch,Destroy,
    GainArmor,GrantHealthRule,GrantKeyword,InvokeBehavior,RequestChoice,SetStats,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from test_infinite_cost_card import registry as base_registry,P,PLAIN

G='blight.test.'
INFINITE=2147483647


@lru_cache(None)
def registry(role='writer',mode=None):
    r=base_registry.__wrapped__()
    r.register_card(CardDefinition(G+'big','Large minion',CardType.MINION,attack=1,health=30))
    for name,keywords,rules in (
            ('immune',(Keyword.IMMUNE,),()),('shield',(Keyword.DIVINE_SHIELD,),()),
            ('cap',(),(HealthRule(HealthFlow.DAMAGE,HealthOp.CAP,1,layer=HealthLayer.TARGET,target_relation='self',target_kinds=(CardType.HERO,)),)),
            ('prevent',(),(HealthRule(HealthFlow.DAMAGE,HealthOp.PREVENT,layer=HealthLayer.TARGET,target_relation='self',target_kinds=(CardType.HERO,)),))):
        r.register_card(CardDefinition(G+name,name,CardType.HERO,health=30,keywords=keywords,health_rules=rules))
    def source(c):return c.state.players[c.player_id].board[-1]
    def strike(c,amount):return (Damage(c.target_id,amount,source(c),DamageKind.MINION_ABILITY),)
    bodies={
        'fill':lambda c:(),
        'strike':lambda c:strike(c,3), 'zero':lambda c:strike(c,0),
        'untargeted':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,3,source(c),DamageKind.MINION_ABILITY),),
        'attack_value':lambda c:strike(c,c.state.entities[source(c)].attack),
        'infinite':lambda c:(SetStats(source(c),attack=INFINITE,source_id=c.source_id),),
        'armor':lambda c:(GainArmor(3-c.player_id,50),),
        'lifesteal':lambda c:(GrantKeyword(source(c),Keyword.LIFESTEAL,c.source_id),),
        'hurt_self':lambda c:(Damage(c.state.players[c.player_id].hero_id,5,c.source_id,DamageKind.SPELL),),
        'double':lambda c:(GrantHealthRule(source(c),HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,source_relation='self'),c.source_id),),
        'morph':lambda c:(Transform(source(c),PLAIN),),
        'grant_native':lambda c:(GrantHealthRule(source(c),RULE,c.source_id),),
        'unknown':lambda c:(ShuffleGeneratedCopies(3-c.player_id,c.player_id,'missing.blight.card',INFINITE,c.source_id),),
        'simultaneous':lambda c:(DamageBatch((Damage(source(c),8,source(c),DamageKind.MINION_ABILITY),Damage(c.target_id,3,source(c),DamageKind.MINION_ABILITY))),),
        'sequential':lambda c:(Damage(source(c),8,source(c),DamageKind.MINION_ABILITY),Damage(c.target_id,3,source(c),DamageKind.MINION_ABILITY)),
    }
    for name,body in bodies.items():
        r.register_behavior(G+name,body)
        target=TargetSpec() if name in ('strike','zero','attack_value','simultaneous','sequential') else None
        r.register_card(CardDefinition(G+name,name,CardType.SPELL,on_play=G+name,targeting=target))
    if mode:
        def watch(c):
            if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!=CARD:return ()
            if mode=='insert_wait':
                if c.state.deck_shuffle_history[-1].first_card.entity_id!=c.event.target_id:return ()
            elif c.state.entities[c.event.target_id].kind!=CardType.HERO:return ()
            if mode=='kill':return (Destroy(c.event.source_id,c.source_id),)
            if mode=='control':return (ChangeControl(c.event.source_id,3-c.player_id),)
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(G+'watch',watch)
        r.register_card(CardDefinition(G+'watch','Observer',CardType.MINION,health=30,
            triggers=(TriggerSpec('card_added_to_deck' if mode=='insert_wait' else 'health_resolved',G+'watch'),)))
    r.validate();r.freeze();return r


class BlightReplacementTests(unittest.TestCase):
    def game(self,hand=(G+'strike',),*,board=(CARD,),enemy_board=(),enemy_deck=(),enemy_hand=(),enemy_hero='HERO_08',mode=None,seat=1):
        own=PlayerSetup('HERO_08',hand=hand,board=(*((G+'watch',) if mode else ()),*board),deck=(G+'fill',)*5,
            mana=10,max_mana=10)
        other=PlayerSetup(enemy_hero,hand=enemy_hand,board=enemy_board,deck=enemy_deck,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other) if seat==1 else (other,own),active_player=seat,seed=287),registry('writer',mode))
    def hand(self,g,cid):return next(i for i in g.state.players[g.state.active_player].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.hand(g,cid);g.apply(PlayCard(g.state.active_player,eid,target));return eid
    def source(self,g):return g.state.players[g.state.active_player].board[-1]
    def hero(self,g,own=False):return g.state.players[g.state.active_player if own else 3-g.state.active_player].hero_id
    def blights(self,g,pid=2):return [i for i in g.state.players[pid].deck if g.state.entities[i].card_id==BLIGHT]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,registry('reader',mode))
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),snap);return other
    def rehash(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')});return snap

    def test_a01_full_root_and_existing_blight_are_kept_without_duplicate_token_adapter(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),4);self.assertEqual(len(d['existing_dependencies']),1)
        r=registry();card=r.card(CARD);self.assertEqual((card.cost,card.attack,card.health),(6,8,8))
        self.assertEqual(card.metadata.runes.unholy,1);self.assertIn('undead',card.metadata.tribes)
        self.assertIn(Keyword.CHARGE,card.keywords);self.assertIsNotNone(r.card(BLIGHT).cast_when_drawn)

    def test_a02_actual_six_mana_play_charge_attack_replaces_eight_hero_damage(self):
        g=self.game((CARD,),board=());hero=self.hero(g);eid=self.play(g,CARD);g.apply(Attack(1,eid,hero))
        self.assertEqual(g.state.players[1].mana,4);self.assertEqual(g.state.entities[hero].health,30)
        self.assertEqual(len(self.blights(g)),8);self.assertEqual(g.state.entities[eid].attacks_this_turn,1)

    def test_a03_actual_minion_combat_still_deals_normal_damage_without_blighs(self):
        g=self.game((),enemy_board=(G+'big',));target=g.state.players[2].board[0];g.apply(Attack(1,self.source(g),target))
        self.assertEqual(g.state.entities[target].damage,8);self.assertEqual(g.state.entities[self.source(g)].damage,1);self.assertFalse(self.blights(g))

    def test_a04_other_minion_ability_has_ordinary_hero_damage(self):
        g=self.game(board=(PLAIN,));hero=self.hero(g);self.play(g,G+'strike',hero)
        self.assertEqual(g.state.entities[hero].health,27);self.assertFalse(self.blights(g))

    def test_a05_own_hero_damage_uses_that_heroes_own_deck(self):
        g=self.game();hero=self.hero(g,True);self.play(g,G+'strike',hero)
        self.assertEqual(g.state.entities[hero].health,30);self.assertEqual(len(self.blights(g,1)),3);self.assertFalse(self.blights(g,2))

    def test_a06_zero_budget_has_no_replacement_shuffle_or_rng(self):
        g=self.game((G+'zero',));rng=g.snapshot()['rng_state'];self.play(g,G+'zero',self.hero(g))
        self.assertFalse(g.state.deck_shuffle_history);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_a07_original_modified_damage_controls_exact_count_and_target_cap_policy(self):
        g=self.game((G+'double',G+'strike'));self.play(g,G+'double');self.play(g,G+'strike',self.hero(g))
        self.assertEqual(len(self.blights(g)),6)
        g=self.game(enemy_hero=G+'cap');self.play(g,G+'strike',self.hero(g));self.assertEqual(len(self.blights(g)),1)

    def test_a08_armor_immunity_and_shield_do_not_consume_health_or_shield_under_native_policy(self):
        g=self.game((G+'armor',G+'strike'));hero=self.hero(g);self.play(g,G+'armor');self.play(g,G+'strike',hero)
        self.assertEqual((g.state.entities[hero].health,g.state.entities[hero].armor),(30,50));self.assertEqual(len(self.blights(g)),3)
        for name in ('immune','shield'):
            g=self.game((G+'untargeted',),enemy_hero=G+name);hero=self.hero(g);self.play(g,G+'untargeted')
            self.assertEqual(g.state.entities[hero].health,30);self.assertEqual(len(self.blights(g)),3)
            if name=='shield':self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[hero].keywords)

    def test_a09_prior_rule_prevention_does_not_create_blighs(self):
        g=self.game(enemy_hero=G+'prevent');self.play(g,G+'strike',self.hero(g));self.assertFalse(self.blights(g))

    def test_a10_replaced_damage_does_not_supply_lifesteal_healing(self):
        g=self.game((G+'hurt_self',G+'lifesteal',G+'strike'));self.play(g,G+'hurt_self');self.play(g,G+'lifesteal')
        self.play(g,G+'strike',self.hero(g));self.assertEqual(g.state.entities[self.hero(g,True)].health,25)
        self.assertFalse([e for e in g.events if e.kind=='lifesteal']);self.assertEqual(len(self.blights(g)),3)

    def test_a11_silence_removes_native_rule_and_restores_ordinary_damage(self):
        g=self.game((P+'silence',G+'strike'));self.play(g,P+'silence',self.source(g));self.play(g,G+'strike',self.hero(g))
        self.assertFalse(self.blights(g));self.assertEqual(g.state.entities[self.hero(g)].health,27)

    def test_a12_transform_does_not_let_same_physical_id_keep_old_replacement(self):
        g=self.game((G+'morph',G+'strike'));self.play(g,G+'morph');self.play(g,G+'strike',self.hero(g))
        self.assertFalse(self.blights(g));self.assertEqual(g.state.entities[self.hero(g)].health,27)

    def test_a13_control_change_after_health_acceptance_keeps_original_actor_and_victim(self):
        g=self.game(mode='control');self.play(g,G+'strike',self.hero(g));row=g.state.deck_shuffle_history[-1]
        self.assertEqual((row.actor_id,row.player_id,row.declared_count),(1,2,3));self.assertEqual(row.source.controller,2)
        self.assertEqual(len(self.blights(g)),3);self.portable(g,'control')

    def test_a14_current_and_base_copies_have_independent_native_abilities(self):
        g=self.game((P+'copy',P+'silence',P+'base',G+'strike',G+'strike',G+'strike'));original=self.source(g)
        self.play(g,P+'copy',original);copy=self.source(g);self.play(g,G+'strike',self.hero(g));self.assertEqual(len(self.blights(g)),3)
        self.play(g,P+'silence',copy);self.play(g,G+'strike',self.hero(g));self.assertEqual(len(self.blights(g)),3)
        self.play(g,P+'base',original);self.play(g,G+'strike',self.hero(g));self.assertEqual(len(self.blights(g)),6)

    def test_a15_source_death_after_health_receipt_does_not_cancel_accepted_shuffle(self):
        g=self.game(mode='kill');eid=self.source(g);self.play(g,G+'strike',self.hero(g))
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(len(self.blights(g)),3);self.portable(g,'kill')

    def test_a16_wait_before_shuffle_preserves_typed_count_and_wrong_resume_rollback(self):
        g=self.game(mode='wait');self.play(g,G+'strike',self.hero(g));self.assertIsNotNone(g.state.pending_choice)
        pending=[w for w in (*g._frame.prefix,*g._frame.continuation) if isinstance(w,ShuffleGeneratedCopies)]
        self.assertEqual(len(pending),1);self.assertEqual(pending[0].count,3);self.assertFalse(self.blights(g))
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'wait');self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.blights(g)),3)

    def test_a17_first_insertion_reaction_wait_sees_complete_atomic_shuffle_on_resume(self):
        g=self.game(mode='insert_wait');self.play(g,G+'strike',self.hero(g));self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.blights(g)),3);other=self.portable(g,'insert_wait');rng=g.snapshot()['rng_state']
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_a18_actual_blighs_cast_when_drawn_deal_two_and_compensate_until_fatigue(self):
        g=self.game();self.play(g,G+'strike',self.hero(g));g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,23);self.assertFalse(g.state.players[2].deck)
        self.assertEqual(sum(x.card_id==BLIGHT for x in g.state.cast_history),3);self.portable(g)

    def test_a19_full_hand_burns_original_bligh_without_casting_it(self):
        g=self.game(enemy_hand=(G+'fill',)*10);self.play(g,G+'strike',self.hero(g));g.apply(EndTurn(1))
        self.assertEqual(len(self.blights(g)),2);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(sum(x.card_id==BLIGHT for x in g.state.cast_history),0)

    def test_a20_real_int32_infinite_attack_representation_creates_at_most_ninety_nine(self):
        g=self.game((G+'infinite',G+'attack_value'));self.play(g,G+'infinite');before=g.state.next_entity_id
        self.play(g,G+'attack_value',self.hero(g));self.assertEqual(len(self.blights(g)),99)
        self.assertEqual(g.state.next_entity_id-before,99);self.assertEqual(g.state.deck_shuffle_history[-1].declared_count,INFINITE)

    def test_a21_near_full_and_full_deck_apply_capacity_without_materializing_failed_copies(self):
        for size in (98,99):
            g=self.game((G+'infinite',G+'attack_value'),enemy_deck=(G+'fill',)*size);self.play(g,G+'infinite')
            before=g.snapshot();next_id=g.state.next_entity_id;self.play(g,G+'attack_value',self.hero(g))
            self.assertEqual(len(g.state.players[2].deck),99);self.assertEqual(g.state.next_entity_id-next_id,99-size)
            self.assertEqual(g.state.entities[self.hero(g)].health,30)
            if size==99:self.assertEqual(g.snapshot()['rng_state'],before['rng_state']);self.assertFalse(g.state.deck_shuffle_history)

    def test_a22_unknown_generated_card_is_rejected_even_at_full_capacity(self):
        g=self.game((G+'unknown',),enemy_deck=(G+'fill',)*99);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,G+'unknown')
        self.assertEqual(g.snapshot(),before)
        for count in (-1,True):
            with self.assertRaises(ValueError):ShuffleGeneratedCopies(2,1,BLIGHT,count)

    def test_a23_rehashed_future_queued_source_and_invalid_native_grants_are_rejected(self):
        g=self.game(mode='wait');self.play(g,G+'strike',self.hero(g))
        def altered(rows):return tuple(replace(w,source_id=g.state.next_entity_id) if isinstance(w,ShuffleGeneratedCopies) else w for w in rows)
        frame=replace(g._frame,prefix=altered(g._frame.prefix),continuation=altered(g._frame.continuation));bad=g.snapshot()
        bad['resolution_frame']=FrameCodec(g.mechanics,g.registry).encode(frame)
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(self.rehash(bad),registry('reader','wait'))
        with self.assertRaises(ValueError):replace(RULE,amount=1)
        g=self.game((G+'grant_native',),board=(PLAIN,));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,G+'grant_native')
        self.assertEqual(g.snapshot(),before)

    def test_a24_failure_rollback_and_both_seats_keep_internal_shuffle_material_private(self):
        g=self.game(mode='fail');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate failure'):self.play(g,G+'strike',self.hero(g))
        self.assertEqual(g.snapshot(),before)
        for seat in (1,2):
            g=self.game(seat=seat);self.play(g,G+'strike',self.hero(g));self.assertEqual(len(self.blights(g,3-seat)),3)
            for viewer in (1,2):
                value=json.dumps(g.observe(viewer))
                for key in ('ShuffleGeneratedCopies','first_card','declared_count','_deck_shuffle_scopes','blight_shuffle'):self.assertNotIn(key,value)

    def test_a25_simultaneous_batch_keeps_frozen_source_but_next_batch_cannot_reuse_dead_rule(self):
        for name,health,count in (('simultaneous',30,3),('sequential',27,0)):
            g=self.game((G+name,));self.play(g,G+name,self.hero(g))
            self.assertEqual(g.state.entities[self.hero(g)].health,health);self.assertEqual(len(self.blights(g)),count)
            self.assertEqual(len(g.state.death_history),1)


if __name__=='__main__':unittest.main()
