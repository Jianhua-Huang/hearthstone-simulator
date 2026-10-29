"""Actual exhausted-payment Secrets and original physical Sack custody."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import mana_kidnap_secrets as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.actions import UseHeroPower
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,GainArmor,
    GainTemporaryMana,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,SpendMana,Summon,Transform)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,Resource,RewindSpec,SummonQuantitySpec,TriggerSpec,Zone
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.kidnap_custody import CAPTURED,RETURNED,SPEC
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.replay import build_replay,replay
from hs_sim.local_pool_format import build_cn37_local_pool_format

CROSS,KIDNAP=native.LEAVES
SACK=native.SACK
P='k643.'
A,BATTLE,OTHER,WATCH,DOUBLE=(P+x for x in ('plain','battle','other','watch','double'))
SPEND,ZERO,CONSUME,POP,COPY,FILL,OP,EMPTY,FAIL=(P+x for x in ('spend','zero','consume','pop','copy','fill','op','empty','fail'))


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original K643 reaction')


def sack(c):
    return next((c.state.entities[i]for pid in (1,2)for i in c.state.players[pid].board if c.state.entities[i].card_id==SACK),None)


def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_mana_kidnap_secrets(r)
    def fail(c):raise ValueError('K643 deliberate failure')
    r.register_behavior(FAIL,fail)
    def battle(c):
        if mode=='self_transform':return (Transform(c.source_id,OTHER),)
        if mode=='self_return':return (ReturnToHand(c.source_id),)
        return (GainArmor(c.player_id,5),)
    r.register_behavior(BATTLE,battle)
    for cid,cost,attack,health,extra in ((A,1,4,6,{}),(OTHER,3,2,7,{}),(BATTLE,1,2,4,{'battlecry':BATTLE})):
        if cid==BATTLE and mode=='rewind':extra=dict(extra,keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        if cid==BATTLE and mode=='dormant_guest':extra=dict(extra,dormant_turns=3)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=metadata(tribes=()),**extra))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=10,metadata=metadata(tribes=()),summon_quantities=(SummonQuantitySpec(),)))
    def pop(c):
        target=sack(c);return ()if target is None else(Destroy(target.id,c.source_id),)
    def copy(c):
        target=sack(c)
        return ()if target is None else(CopyMinion(target.id,1,mode='base'if mode=='base_copy'else'current',cause=SummonCause.capture(c)),)
    def op(c):
        target=sack(c)
        if target is None:return ()
        if mode=='silence_sack':return (Silence(target.id),)
        if mode=='transform_sack':return (Transform(target.id,A),)
        if mode=='bounce_sack':return (ReturnToHand(target.id),)
        if mode=='steal_sack':return (ChangeControl(target.id,2),)
        return ()
    for cid,cost,body in ((SPEND,10,lambda c:(GainArmor(c.player_id,1),)),(ZERO,0,lambda c:(GainArmor(c.player_id,1),)),
            (CONSUME,0,lambda c:(SpendMana(c.player_id,source_id=c.source_id),)),(POP,0,pop),(COPY,0,copy),
            (FILL,0,lambda c:tuple(AddToHand(c.player_id,A)for _ in range(10))),(OP,0,op),
            (EMPTY,0,lambda c:(Summon(1,SACK),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata()))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id)
        if mode=='refund' and e.kind=='mana_spent' and e.player_id==2 and source is not None and source.card_id==SPEND:
            return (GainTemporaryMana(2,1),)
        if e.kind=='secret_revealed' and source is not None and source.card_id in native.LEAVES:
            if mode=='reveal_wait':return (prompt(c),)
            if source.card_id==KIDNAP:
                ident=c.state.play_history[-1].source_id
                if mode=='reveal_transform':return (Transform(ident,OTHER),)
                if mode=='reveal_bounce':return (ReturnToHand(ident),)
                if mode=='reveal_transfer':return (ChangeControl(ident,1),)
        if e.kind=='card_drawn' and e.player_id==1:
            if mode=='draw_wait':return (prompt(c),)
            if mode=='draw_lethal':return (Damage(c.state.players[1].hero_id,100,c.source_id),)
            if mode=='draw_fail':return (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        if e.kind=='minion_summoned' and source is not None and source.card_id==SACK:
            if mode=='entry_wait':return (prompt(c),)
            if mode=='entry_destroy':return (Destroy(source.id,c.source_id),)
            if mode=='entry_fail':return (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        if mode=='return_wait' and e.kind=='card_moved_to_hand' and e.player_id==2:return (prompt(c),)
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),triggers=tuple(
        TriggerSpec(kind,WATCH)for kind in ('mana_spent','secret_revealed','card_drawn','minion_summoned','card_moved_to_hand'))))
    return r


class ManaKidnapSecretTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,secret=KIDNAP,*,mode='normal',board=(),enemy=(),owner_hand=1,enemy_max=10,owed=0,owner_deck=None):
        self.mode=mode
        hand=(secret,POP)+(A,)*(owner_hand-1)
        if owner_hand==10:hand=(secret,POP,FILL)+(A,)*7
        g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=(A,)*20 if owner_deck is None else owner_deck,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=(BATTLE,SPEND,ZERO,CONSUME,POP,COPY,FILL,OP,EMPTY),board=enemy,deck=(A,)*20,
                mana=enemy_max,max_mana=enemy_max,overload_owed=owed,hero_power_card_id='warrior.power')),seed=643),registry(mode))
        self.play(g,secret)
        if owner_hand==10:self.play(g,FILL)
        g.apply(EndTurn(1));return g
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def kidnap(self,g):return self.play(g,BATTLE,player=2)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')});return s

    def test_complete_roots_real_sack_and_original_enchantment_are_not_conflated(self):
        d=native.load_batch();self.assertEqual([x['record']['id']for x in d['dependencies']],[CROSS,KIDNAP,SACK])
        self.assertEqual([x['record']['id']for x in d['evidence_only']],['REV_828e'])
        self.assertEqual(len(d['official_observations']),4);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        card=registry().card(SACK);self.assertEqual((card.cost,card.attack,card.health,card.native_deathrattle),(1,0,4,SPEC))

    def test_actual_hand_payment_exhaustion_draws_two_before_paid_spell_body(self):
        g=self.game(CROSS);before=len(g.state.players[1].hand);self.play(g,SPEND,player=2)
        self.assertEqual(len(g.state.players[1].hand),before+2);self.assertEqual(g.state.players[1].secrets,[])
        spent=next(e for e in g.events if e.kind=='mana_spent'and e.player_id==2 and e.amount==10)
        self.assertEqual(dict(spent.data)['_mana_available'],(10,0))
        reveal=next(e.sequence for e in g.events if e.kind=='secret_revealed');armor=next(e.sequence for e in g.events if e.kind=='armor_gained'and e.player_id==2)
        self.assertLess(reveal,armor);self.portable(g)

    def test_zero_available_from_overload_and_zero_payment_do_not_trigger(self):
        g=self.game(CROSS,enemy_max=0,owed=1);self.assertEqual(g.state.players[2].mana,0);self.play(g,ZERO,player=2)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(any(e.kind=='secret_revealed'for e in g.events))

    def test_positive_remaining_mana_and_own_payments_keep_secret(self):
        g=self.game(CROSS);self.play(g,ZERO,player=2);self.assertEqual(len(g.state.players[1].secrets),1)
        self.play(g,BATTLE,player=2);self.assertEqual(len(g.state.players[1].secrets),1)

    def test_explicit_mana_consumption_uses_existing_original_result(self):
        g=self.game(CROSS);before=len(g.state.players[1].hand);self.play(g,CONSUME,player=2)
        self.assertEqual(len(g.state.players[1].hand),before+2);self.assertEqual(g.state.mana_consumption_history[-1].mana_after,0)
        self.assertEqual(g.state.players[1].secrets,[])

    def test_hero_power_payment_can_exhaust_mana_and_trigger_before_body(self):
        g=self.game(CROSS,enemy_max=1);self.assertEqual(g.state.players[2].mana,2);before=len(g.state.players[1].hand)
        g.apply(UseHeroPower(2,g.state.players[2].hero_power_id))
        self.assertEqual(len(g.state.players[1].hand),before+2);self.assertEqual(g.state.players[1].secrets,[]);self.portable(g)

    def test_original_expenditure_survives_an_earlier_refund_listener(self):
        g=self.game(CROSS,mode='refund',enemy=(WATCH,));before=len(g.state.players[1].hand);self.play(g,SPEND,player=2)
        self.assertEqual(g.state.players[2].mana,1);self.assertEqual(len(g.state.players[1].hand),before+2);self.assertEqual(g.state.players[1].secrets,[])

    def test_official_full_hand_gate_keeps_secret_but_one_space_draws_and_burns(self):
        for count in (9,10):
            with self.subTest(count=count):
                g=self.game(CROSS,owner_hand=count);self.assertEqual(len(g.state.players[1].hand),count);self.play(g,SPEND,player=2)
                self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.players[1].secrets),int(count==10))
                draws=[x for x in g.state.draw_history if x.player_id==1]
                self.assertEqual(len(draws),2 if count==9 else 0)

    def test_full_owner_board_does_not_block_cross_draw(self):
        g=self.game(CROSS,board=(A,)*7);before=len(g.state.players[1].hand);self.play(g,SPEND,player=2)
        self.assertEqual(len(g.state.players[1].hand),before+2);self.assertEqual(g.state.players[1].secrets,[])

    def test_draw_or_reveal_wait_restores_clones_replays_original_paid_action(self):
        for mode in ('draw_wait','reveal_wait'):
            with self.subTest(mode=mode):
                g=self.game(CROSS,mode=mode,board=(WATCH,));self.play(g,SPEND,player=2);self.assertIsNotNone(g.state.pending_choice)
                other=self.portable(g);self.settle(g);self.settle(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_draw_reaction_failure_rolls_back_payment_secret_and_rng(self):
        g=self.game(CROSS,mode='draw_fail',board=(WATCH,));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K643 deliberate'):self.play(g,SPEND,player=2)
        self.assertEqual(g.snapshot(),saved)

    def test_terminal_draw_reaction_interrupts_original_unstarted_paid_body(self):
        g=self.game(CROSS,mode='draw_lethal',board=(WATCH,));self.play(g,SPEND,player=2)
        self.assertNotEqual(g.state.status,'playing');self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        self.assertEqual(g.state.players[2].mana,0);self.portable(g)

    def test_rehashed_mana_endpoints_reject_arithmetic_and_original_quote_mismatch(self):
        g=self.game(CROSS);self.play(g,SPEND,player=2);base=g.snapshot()
        for endpoints in ([11,0],[11,1],None):
            with self.subTest(endpoints=endpoints):
                s=json.loads(json.dumps(base));event=next(e for e in s['events']if e['kind']=='mana_spent'and e['player_id']==2 and e['amount']==10)
                event['data']['_mana_available']=endpoints
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())

    def test_kidnap_runs_battlecry_then_silently_stores_same_original_and_real_sack(self):
        g=self.game();ident=self.kidnap(g);holder=self.entity(g,SACK,1,'board');guest=g.state.entities[ident]
        self.assertEqual((holder.attack,holder.health,guest.zone),(0,4,Zone.SETASIDE))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,5)
        self.assertFalse(any(row.entity_id==ident for row in g.state.death_history));self.assertEqual(g.state.players[2].resources[Resource.CORPSES],0)
        memory=next(a.deathrattle_memory for a in holder.abilities if a.deathrattle_memory is not None)
        self.assertEqual(memory.custody.stored.entity_id,ident);self.assertEqual(memory.custody.reference,g.state.play_history[-1].minion_entry.reference)
        self.assertEqual(sum(e.kind==CAPTURED for e in g.events),1);self.portable(g)

    def test_ordinary_combat_sack_death_returns_original_without_a_second_battlecry(self):
        g=self.game(enemy=(A,));ident=self.kidnap(g);holder=self.entity(g,SACK,1,'board');attacker=self.entity(g,A,2,'board')
        g.apply(Attack(2,attacker.id,holder.id));self.assertEqual(g.state.entities[ident].zone,Zone.HAND)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,5);self.assertEqual(sum(e.kind==RETURNED for e in g.events),1)
        self.play(g,BATTLE,player=2);self.assertEqual(g.state.entities[ident].zone,Zone.BOARD);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,10);self.portable(g)

    def test_full_owner_board_keeps_kidnap_and_original_minion(self):
        g=self.game(board=(A,)*7);ident=self.kidnap(g)
        self.assertEqual(g.state.entities[ident].zone,Zone.BOARD);self.assertEqual(len(g.state.players[1].secrets),1)

    def test_dormant_or_departed_played_minion_does_not_become_an_unrelated_captive(self):
        for mode in ('dormant_guest','self_return'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);ident=self.kidnap(g)
                self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(any(e.kind==CAPTURED for e in g.events))

    def test_reveal_same_residence_transform_or_transfer_keeps_original_physical_subject(self):
        for mode in ('self_transform','reveal_transform','reveal_transfer'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,board=(WATCH,));ident=self.kidnap(g);self.assertEqual(g.state.entities[ident].zone,Zone.SETASIDE)
                self.play(g,POP,player=2);self.assertEqual((g.state.entities[ident].zone,g.state.entities[ident].controller),(Zone.HAND,2))
                if mode!='reveal_transfer':self.assertEqual(g.state.entities[ident].card_id,OTHER)
                self.portable(g)

    def test_reveal_departure_consumes_secret_without_capturing_hand_or_new_minion(self):
        g=self.game(mode='reveal_bounce',board=(WATCH,));ident=self.kidnap(g)
        self.assertEqual(g.state.entities[ident].zone,Zone.HAND);self.assertEqual(g.state.players[1].secrets,[])
        self.assertFalse(any(e.kind==CAPTURED for e in g.events));self.assertFalse(any(g.state.entities[i].card_id==SACK for i in g.state.players[1].board))

    def test_entry_death_has_memory_before_reaction_and_releases_actual_original(self):
        g=self.game(mode='entry_destroy',board=(WATCH,));ident=self.kidnap(g)
        self.assertEqual(g.state.entities[ident].zone,Zone.HAND);self.assertEqual(sum(e.kind==RETURNED for e in g.events),1);self.portable(g)

    def test_quantity_and_current_copies_share_only_one_physical_captive_claim(self):
        for copied in (False,True):
            with self.subTest(copied=copied):
                g=self.game(board=()if copied else(DOUBLE,));ident=self.kidnap(g)
                if copied:self.play(g,COPY,player=2)
                self.assertEqual(sum(g.state.entities[i].card_id==SACK for i in g.state.players[1].board),2)
                self.play(g,POP,player=2);g.apply(EndTurn(2));self.play(g,POP)
                self.assertEqual(g.state.entities[ident].zone,Zone.HAND);self.assertEqual(sum(e.kind==RETURNED for e in g.events),1);self.portable(g)

    def test_empty_or_base_copied_sack_does_not_invent_a_captive(self):
        g=self.game(mode='base_copy');ident=self.kidnap(g);self.play(g,COPY,player=2)
        self.play(g,POP,player=2);g.apply(EndTurn(2));self.play(g,POP);self.assertEqual(sum(e.kind==RETURNED for e in g.events),1)
        self.assertEqual(g.state.entities[ident].zone,Zone.HAND)
        g=self.game();self.play(g,EMPTY,player=2);self.play(g,POP,player=2)
        self.assertFalse(any(e.kind==RETURNED for e in g.events));self.assertEqual(len(g.state.players[1].secrets),1)

    def test_silence_transform_and_bounce_use_normal_carrier_lifecycle(self):
        for mode in ('silence_sack','transform_sack','bounce_sack'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);ident=self.kidnap(g);self.play(g,OP,player=2);self.play(g,POP,player=2)
                self.assertEqual(g.state.entities[ident].zone,Zone.SETASIDE);self.assertFalse(any(e.kind==RETURNED for e in g.events));self.portable(g)

    def test_stolen_sack_uses_current_actual_deathrattle_controller_opponent_policy(self):
        g=self.game(mode='steal_sack');ident=self.kidnap(g);self.play(g,OP,player=2);self.play(g,POP,player=2)
        self.assertEqual((g.state.entities[ident].zone,g.state.entities[ident].controller,g.state.entities[ident].owner),(Zone.HAND,1,2));self.portable(g)

    def test_full_recipient_hand_burns_same_original_without_minion_death_or_reclaim(self):
        g=self.game();ident=self.kidnap(g);self.play(g,FILL,player=2);self.assertEqual(len(g.state.players[2].hand),10)
        g.apply(EndTurn(2));self.play(g,POP);self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD)
        self.assertFalse(any(row.entity_id==ident for row in g.state.death_history));self.assertEqual(g.state.players[2].resources[Resource.CORPSES],0);self.portable(g)

    def test_reveal_entry_and_actual_return_waits_restore_clone_and_replay(self):
        for mode in ('reveal_wait','entry_wait','return_wait'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,board=(WATCH,));ident=self.kidnap(g)
                if mode=='return_wait':self.play(g,POP,player=2)
                self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);self.settle(g);self.settle(other)
                self.assertEqual(g.snapshot(),other.snapshot())
                self.assertEqual(g.state.entities[ident].zone,Zone.HAND if mode=='return_wait'else Zone.SETASIDE)

    def test_entry_and_resume_failures_roll_back_original_custody_payment_and_rng(self):
        g=self.game(mode='entry_fail',board=(WATCH,));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K643 deliberate'):self.kidnap(g)
        self.assertEqual(g.snapshot(),saved)
        g=self.game(mode='entry_wait',board=(WATCH,));self.kidnap(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K643 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.settle(g)

    def test_rehashed_captive_memory_cannot_borrow_future_or_other_play_source(self):
        g=self.game();self.kidnap(g);base=g.snapshot();holder=self.entity(g,SACK,1,'board').id
        for change in ('epoch','play','source','event'):
            with self.subTest(change=change):
                s=json.loads(json.dumps(base));entity=next(e for e in s['state']['entities']if e['id']==holder)if isinstance(s['state']['entities'],list)else s['state']['entities'][str(holder)]
                memory=next(a['deathrattle_memory']for a in entity['abilities']if a['deathrattle_memory']is not None)
                if change=='epoch':memory['custody']['stored']['zone_epoch']+=99
                elif change=='play':memory['custody']['play_id']=1
                elif change=='source':memory['custody']['source']['card_id']=CROSS
                else:next(e for e in s['events']if e['kind']==CAPTURED)['data']['_custody']='{}'
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())

    def test_real_rewind_discards_old_custody_and_recreates_actual_sack_once(self):
        g=self.game(mode='rewind');ident=self.kidnap(g);self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g,'retry')
        self.assertEqual(g.state.entities[ident].zone,Zone.SETASIDE);self.assertEqual(sum(g.state.entities[i].card_id==SACK for i in g.state.players[1].board),1)
        self.assertEqual(sum(e.kind==CAPTURED for e in g.events),2);self.play(g,POP,player=2);self.portable(g)

    def test_player_views_hide_internal_captive_and_payment_allocations(self):
        g=self.game();self.kidnap(g)
        for pid in (1,2):
            view=json.dumps(g.for_player(pid).observe())
            for key in ('"custody"','_custody','_mana_available','next_entity_id','submitted_cost'):self.assertNotIn(key,view)

    def test_full_bound_host_both_real_secrets_and_sack_release_restore_and_replay(self):
        fmt=host_format();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CROSS,KIDNAP,'CS2_029'),deck=('CS2_120',)*10,mana=10,max_mana=10),
            PlayerSetup('HERO_01',hand=('CS2_029','CS2_029','CS2_120'),deck=('CS2_120',)*10,mana=10,max_mana=10)),seed=643,generation_context=fmt.context),fmt.registry)
        self.play(g,CROSS);self.play(g,KIDNAP);g.apply(EndTurn(1))
        self.play(g,'CS2_029',target=g.state.players[1].hero_id,player=2);self.play(g,'CS2_029',target=g.state.players[1].hero_id,player=2)
        ident=self.play(g,'CS2_120',player=2);self.assertEqual(g.state.players[1].secrets,[]);self.assertEqual(g.state.entities[ident].zone,Zone.SETASIDE)
        g.apply(EndTurn(2));self.play(g,'CS2_029',target=self.entity(g,SACK,1,'board').id)
        self.assertEqual(g.state.entities[ident].zone,Zone.HAND);saved=g.snapshot();reader=build_cn37_local_pool_format().registry
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)


@lru_cache(None)
def host_format():return build_cn37_local_pool_format()


if __name__=='__main__':unittest.main()
