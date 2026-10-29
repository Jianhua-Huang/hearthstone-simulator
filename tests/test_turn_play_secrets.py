"""Real end-turn Secret and original pre-Battlecry minion entry consumers."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import turn_play_secrets as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,GainArmor,GainTemporaryMana,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,RewindSpec,SecretSpec,SummonQuantitySpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.sacrifice import DestroyCapturedMinion
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.local_pool_format import build_cn37_local_pool_format

P='k642.'
A,BATTLE,TOKEN,THREE,OTHER,SLEEP,WATCH,DOUBLE=(P+x for x in ('plain','battle','token','three','other','sleep','watch','double'))
SPEND,SPEND8,GAIN,GENERATE,FAIL,PAUSE=(P+x for x in ('spend','spend8','gain','generate','fail','pause'))
MEANING,TRIAL=native.LEAVES
CTX=GenerationContext('cn37-k642-complete','standard')


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),
        source_id=c.source_id,prompt='Original K642 entry')


def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_turn_play_secrets(r)
    def fail(c):raise ValueError('K642 deliberate failure')
    r.register_behavior(FAIL,fail)
    def battle(c):
        if mode=='tokens':return (Summon(c.player_id,TOKEN),Summon(c.player_id,TOKEN))
        if mode=='remove_others':return tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board if i!=c.source_id)
        if mode=='self_transform':return (Transform(c.source_id,OTHER),)
        if mode=='self_return':return (ReturnToHand(c.source_id),)
        if mode=='self_transfer':return (ChangeControl(c.source_id,1),)
        if mode=='battlecry_wait':return (prompt(c),GainArmor(c.player_id,5))
        if mode=='battlecry_fail':return (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        return (GainArmor(c.player_id,5),)
    r.register_behavior(BATTLE,battle)
    r.register_behavior(THREE,lambda c:(GainArmor(c.player_id,99),))
    for cid,cost,attack,health,extra in ((A,1,1,4,{}),(BATTLE,1,4,5,{'battlecry':BATTLE}),
        (TOKEN,0,1,1,{}),(THREE,3,3,6,{'battlecry':THREE}),(OTHER,3,2,7,{}),
        (SLEEP,3,3,4,{'dormant_turns':3})):
        if cid==BATTLE and mode=='protected':extra=dict(extra,keywords=(Keyword.DIVINE_SHIELD,Keyword.REBORN))
        if cid==BATTLE and mode=='rewind':extra=dict(extra,keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=metadata(tribes=()),**extra))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=10,metadata=metadata(tribes=()),summon_quantities=(SummonQuantitySpec(),)))
    for cid,cost,body in ((SPEND,10,lambda c:(GainArmor(c.player_id,1),)),
            (SPEND8,8,lambda c:(GainArmor(c.player_id,1),)),
            (GAIN,0,lambda c:(GainTemporaryMana(c.player_id,1),)),
            (GENERATE,0,lambda c:(Summon(c.player_id,A),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=metadata()))
    def watch(c):
        event=c.event;source=c.state.entities.get(event.source_id)
        if event.kind=='secret_revealed' and source is not None and source.card_id in (MEANING,TRIAL,PAUSE):
            if mode=='reveal_wait':return (prompt(c),)
            if mode=='reveal_mana' and source.card_id==MEANING:return (GainTemporaryMana(2,1),)
            if source.card_id==TRIAL:
                ident=c.state.play_history[-1].source_id
                if mode=='reveal_transform':return (Transform(ident,OTHER),)
                if mode=='reveal_transfer':return (ChangeControl(ident,1),)
                if mode=='reveal_bounce':return (ReturnToHand(ident),)
        if event.kind=='minion_play_accepted' and mode=='pre_battlecry_wait':return (prompt(c),)
        if event.kind=='minion_summoned' and source is not None and source.card_id in (THREE,OTHER,SLEEP):
            if mode=='entry_wait':return (prompt(c),)
            if mode=='entry_fail':return (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=tuple(TriggerSpec(kind,WATCH)for kind in ('secret_revealed','minion_summoned','minion_play_accepted'))))
    members=[]if mode=='empty'else[PoolMember(SLEEP if mode=='sleep'else THREE,2)]
    if mode=='weighted':members.append(PoolMember(OTHER,5))
    for cid in {m.card_id for m in members}:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='unknown':
        members=[];unknown=CardDefinition(P+'unknown',P+'unknown',CardType.MINION,cost=3,attack=2,health=4,metadata=metadata(tribes=()))
        r.register_pool_card(PoolCard.from_definition(unknown));members.append(PoolMember(unknown.id))
    r.register_pool(PoolDefinition('constructed.cards','k642-complete-fixture-'+mode,CTX.target_id,CTX.mode,tuple(members),complete=True))
    r.register_secret_condition(PAUSE,lambda c:native.trial_recipient(c)is not None)
    r.register_behavior(PAUSE,lambda c:(prompt(c),DestroyCapturedMinion(native.trial_recipient(c),c.source_id)))
    r.register_card(CardDefinition(PAUSE,PAUSE,CardType.SPELL,keywords=(Keyword.SECRET,),
        secret=SecretSpec(PAUSE,('card_played',),PAUSE,PAUSE),metadata=metadata()))
    return r


class TurnPlaySecretTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,secret=TRIAL,*,board=(),enemy=(A,A,A),mode='normal',context=CTX):
        self.mode=mode
        g=Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=(secret,SPEND8,A),board=board,deck=(A,)*15,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=(BATTLE,SPEND,GAIN,GENERATE,A),board=enemy,deck=(A,)*15,mana=10,max_mana=10)),
            seed=642,generation_context=context),registry(mode))
        self.play(g,secret);g.apply(EndTurn(1));return g
    def end_zero(self,g):self.play(g,SPEND,player=2);g.apply(EndTurn(2))
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')});return s

    def test_complete_raw_roots_four_primary_faces_and_explicit_name_alias(self):
        d=native.load_batch();self.assertEqual([x['record']['id']for x in d['dependencies']],list(native.LEAVES))
        self.assertEqual({(x['card_id'],x['locale'])for x in d['official_observations']},{(cid,loc)for cid in native.LEAVES for loc in ('zh_CN','en_US')})
        self.assertEqual((d['known_name_aliases'][0]['raw_name'],d['known_name_aliases'][0]['official_name']),('神圣试炼','审判'))
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_trial_after_real_battlecry_destroys_only_original_played_minion(self):
        g=self.game();ident=self.play(g,BATTLE,player=2);row=g.state.play_history[-1]
        self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,5)
        self.assertTrue(row.completed);self.assertEqual(row.minion_entry.reference.entity_id,ident);self.assertEqual(row.minion_entry.other_minion_count,3)
        self.assertEqual(len(g.state.players[2].board),3);self.assertEqual(g.state.players[1].secrets,[]);self.portable(g)
        for pid in (1,2):
            view=json.dumps(g.for_player(pid).observe());self.assertNotIn('minion_entry',view);self.assertNotIn('_entry_other_minions',view)

    def test_battlecry_tokens_do_not_backfill_original_three_minion_threshold(self):
        g=self.game(enemy=(A,A),mode='tokens');ident=self.play(g,BATTLE,player=2)
        self.assertEqual(len(g.state.players[2].board),5);self.assertEqual(g.state.entities[ident].zone,Zone.BOARD)
        self.assertEqual(g.state.play_history[-1].minion_entry.other_minion_count,2);self.assertEqual(len(g.state.players[1].secrets),1)

    def test_original_threshold_survives_battlecry_removing_other_minions(self):
        g=self.game(mode='remove_others');ident=self.play(g,BATTLE,player=2)
        self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[2].board,[])
        self.assertEqual(g.state.play_history[-1].minion_entry.other_minion_count,3);self.portable(g)

    def test_dormant_does_not_count_in_explicit_local_original_threshold(self):
        g=self.game(enemy=(A,A,SLEEP));ident=self.play(g,BATTLE,player=2)
        self.assertEqual(g.state.play_history[-1].minion_entry.other_minion_count,2)
        self.assertEqual(g.state.entities[ident].zone,Zone.BOARD);self.assertEqual(len(g.state.players[1].secrets),1)

    def test_generated_summon_is_not_a_physical_played_minion(self):
        g=self.game();self.play(g,GENERATE,player=2)
        self.assertEqual(len(g.state.players[2].board),4);self.assertEqual(len(g.state.players[1].secrets),1)
        self.assertIsNone(g.state.play_history[-1].minion_entry)

    def test_trial_does_not_trigger_on_owner_play_or_a_spell(self):
        g=self.game();self.play(g,GAIN,player=2);self.assertEqual(len(g.state.players[1].secrets),1)
        g.apply(EndTurn(2));self.play(g,A);self.assertEqual(len(g.state.players[1].secrets),1)

    def test_battlecry_same_residence_transform_and_transfer_keep_original_victim(self):
        for mode in ('self_transform','self_transfer'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);ident=self.play(g,BATTLE,player=2)
                self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].secrets,[]);self.portable(g)

    def test_battlecry_departure_keeps_secret_and_does_not_destroy_returned_hand(self):
        g=self.game(mode='self_return');ident=self.play(g,BATTLE,player=2)
        self.assertEqual(g.state.entities[ident].zone,Zone.HAND);self.assertEqual(len(g.state.players[1].secrets),1);self.portable(g)

    def test_reveal_transform_or_transfer_still_destroys_same_residence(self):
        for mode in ('reveal_transform','reveal_transfer'):
            with self.subTest(mode=mode):
                g=self.game(board=(WATCH,),mode=mode);ident=self.play(g,BATTLE,player=2)
                self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].secrets,[]);self.portable(g)

    def test_reveal_departure_consumes_secret_without_destroying_hand_residence(self):
        g=self.game(board=(WATCH,),mode='reveal_bounce');ident=self.play(g,BATTLE,player=2)
        self.assertEqual(g.state.entities[ident].zone,Zone.HAND);self.assertEqual(g.state.players[1].secrets,[]);self.portable(g)

    def test_trial_works_with_full_secret_owner_board(self):
        g=self.game(board=(A,)*7);ident=self.play(g,BATTLE,player=2)
        self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].board),7)

    def test_trial_ordinary_destruction_bypasses_shield_and_reborn_keeps_original_play(self):
        g=self.game(mode='protected');ident=self.play(g,BATTLE,player=2)
        self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD)
        reborn=self.entity(g,BATTLE,2,'board');self.assertNotEqual(reborn.id,ident);self.assertEqual(reborn.health,1)
        self.assertEqual(g.state.play_history[-1].minion_entry.reference.entity_id,ident)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,5);self.portable(g)

    def test_failure_after_actual_entry_rolls_back_original_payment_history_and_rng(self):
        g=self.game(mode='battlecry_fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K642 deliberate'):self.play(g,BATTLE,player=2)
        self.assertEqual(g.snapshot(),saved)

    def test_real_rewind_restores_secret_and_accepts_only_surviving_original_entry(self):
        g=self.game(mode='rewind');ident=self.play(g,BATTLE,player=2)
        self.assertIsNotNone(g.state.pending_choice);first=g.state.play_history[-1].minion_entry
        self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD);self.portable(g);self.choose(g,'retry')
        current=g.state.play_history[-1].minion_entry
        self.assertGreater(current.reference.presence_id,first.reference.presence_id)
        self.assertEqual(current.reference.entity_id,ident);self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].secrets,[]);self.assertEqual(len(g.state.play_history),2)
        self.assertEqual(sum(e.kind=='minion_play_accepted'for e in g.events),2);self.portable(g)

    def test_pre_battlecry_and_reveal_wait_restore_clone_and_replay_original_fact(self):
        for mode in ('pre_battlecry_wait','battlecry_wait','reveal_wait'):
            with self.subTest(mode=mode):
                g=self.game(board=(WATCH,),mode=mode);ident=self.play(g,BATTLE,player=2)
                self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.play_history[-1].minion_entry.other_minion_count,3)
                other=self.portable(g);self.settle(g);self.settle(other)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD)

    def test_original_entry_and_private_event_reject_rehashed_corruption(self):
        g=self.game();self.play(g,BATTLE,player=2);base=g.snapshot()
        for key in ('drop','count','duplicate','future','recipient','event'):
            with self.subTest(key=key):
                s=json.loads(json.dumps(base));row=s['state']['play_history'][-1];entry=row['minion_entry']
                if key=='drop':row['minion_entry']=None
                elif key=='count':entry['other_minions'].pop()
                elif key=='duplicate':entry['other_minions'][1]=dict(entry['other_minions'][0])
                elif key=='future':entry['reference']['presence_id']=s['state']['next_order']
                elif key=='recipient':entry['reference']['entity_id']=entry['other_minions'][0]['entity_id']
                else:next(e for e in s['events']if e['kind']=='minion_play_accepted')['data']['_entry_other_minions'].pop()
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())

    def test_created_destruction_effect_rejects_future_original_presence(self):
        g=self.game(PAUSE);self.play(g,BATTLE,player=2);self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        s=json.loads(json.dumps(g.snapshot()))
        def mutate(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.DestroyCapturedMinion'):
                    value['fields']['victim']['fields']['presence_id']=s['state']['next_order'];return True
                return any(mutate(v)for v in value.values())
            return isinstance(value,list)and any(mutate(v)for v in value)
        self.assertTrue(mutate(s['resolution_frame']))
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),registry())

    def test_meaning_zero_mana_opponent_end_summons_before_next_owner_start(self):
        g=self.game(MEANING,enemy=());self.end_zero(g);root=g.state.card_summon_history[-1];ident=root.deliveries[0].entity.entity_id
        self.assertEqual((g.state.active_player,g.state.turn),(1,3));self.assertEqual(g.state.entities[ident].card_id,THREE)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.assertIsNone(root.request.pool_basis.attack_window)
        self.assertNotIn(Keyword.CHARGE,g.state.entities[ident].keywords)
        g.apply(Attack(1,ident,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        self.assertEqual(g.state.players[1].secrets,[]);self.portable(g)

    def test_meaning_positive_or_temporary_mana_keeps_secret_without_rng(self):
        for temporary in (False,True):
            with self.subTest(temporary=temporary):
                g=self.game(MEANING,enemy=());
                if temporary:self.play(g,SPEND,player=2);self.play(g,GAIN,player=2)
                rng=g._rng.getstate();g.apply(EndTurn(2))
                self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.card_summon_history,[])

    def test_meaning_owner_zero_end_does_not_trigger(self):
        self.mode='normal';g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=(MEANING,SPEND8),deck=(A,)*10,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',deck=(A,)*10)),seed=642,generation_context=CTX),registry())
        self.play(g,MEANING);self.play(g,SPEND8);self.assertEqual(g.state.players[1].mana,0);g.apply(EndTurn(1))
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(g.state.card_summon_history,[])

    def test_meaning_full_board_keeps_secret_without_random_draw(self):
        g=self.game(MEANING,board=(A,)*7,enemy=());self.play(g,SPEND,player=2);rng=g._rng.getstate();g.apply(EndTurn(2))
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.card_summon_history,[])

    def test_meaning_empty_complete_domain_consumes_secret_without_rng(self):
        g=self.game(MEANING,enemy=(),mode='empty');self.play(g,SPEND,player=2);rng=g._rng.getstate();g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].secrets,[]);self.assertEqual(g._rng.getstate(),rng);self.assertIsNone(g.state.card_summon_history[-1].selected)

    def test_meaning_complete_weighted_basis_and_quantity_are_shared(self):
        g=self.game(MEANING,board=(DOUBLE,),enemy=(),mode='weighted');self.end_zero(g);row=g.state.card_summon_history[-1]
        self.assertEqual({x.card_id:x.weight for x in row.request.pool_basis.candidates},{THREE:2,OTHER:5})
        self.assertEqual(row.plan.total,2);self.assertEqual(len(row.deliveries),2)
        self.assertEqual(len({g.state.entities[x.entity.entity_id].card_id for x in row.deliveries}),1)

    def test_meaning_dormant_candidate_is_kept_and_uses_native_entry(self):
        g=self.game(MEANING,enemy=(),mode='sleep');self.end_zero(g)
        self.assertEqual(self.entity(g,SLEEP,1,'board').active,False);self.assertEqual(g.state.players[1].secrets,[])

    def test_meaning_reveal_and_entry_wait_restore_clone_replay_then_end(self):
        for mode in ('reveal_wait','entry_wait'):
            with self.subTest(mode=mode):
                g=self.game(MEANING,board=(WATCH,),enemy=(),mode=mode);self.end_zero(g)
                self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);self.settle(g);self.settle(other)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.active_player,1)

    def test_meaning_accepted_zero_gate_survives_reveal_mana_change(self):
        g=self.game(MEANING,board=(WATCH,),enemy=(),mode='reveal_mana');self.end_zero(g)
        self.assertEqual(len(g.state.card_summon_history),1);self.assertEqual(g.state.players[1].secrets,[])

    def test_end_action_failure_restores_secret_clocks_history_and_rng(self):
        g=self.game(MEANING,board=(WATCH,),enemy=(),mode='entry_fail');self.play(g,SPEND,player=2);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K642 deliberate'):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),saved)

    def test_failed_entry_choice_restores_then_finishes_without_another_pool_draw(self):
        g=self.game(MEANING,board=(WATCH,),enemy=(),mode='entry_wait');self.end_zero(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K642 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.settle(g);self.assertEqual(len(g.state.card_summon_history),1);self.assertEqual(g.state.active_player,1)

    def test_unknown_and_unbound_domains_fail_explicitly_without_cropping_or_partial_end(self):
        for mode,context in (('unknown',CTX),('normal',None)):
            with self.subTest(mode=mode):
                g=self.game(MEANING,enemy=(),mode=mode,context=context);self.play(g,SPEND,player=2);saved=g.snapshot()
                with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):g.apply(EndTurn(2))
                self.assertEqual(g.snapshot(),saved)

    def test_full_bound_host_executes_both_real_secret_roots(self):
        for secret in native.LEAVES:
            with self.subTest(secret=secret):
                fmt=host_format();g=Game.from_scenario(Scenario((
                    PlayerSetup('HERO_08',hand=(secret,),deck=('CS2_120',)*10,mana=10,max_mana=10),
                    PlayerSetup('HERO_01',hand=('CS2_029','CS2_029','CS2_120','CS2_120'),board=('CS2_120',)*3,deck=('CS2_120',)*10,mana=10,max_mana=10)),
                    seed=642,generation_context=fmt.context),fmt.registry)
                self.play(g,secret);g.apply(EndTurn(1))
                if secret==TRIAL:
                    ident=self.play(g,'CS2_120',player=2);self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD)
                else:
                    self.play(g,'CS2_029',target=g.state.players[1].hero_id,player=2)
                    self.play(g,'CS2_029',target=g.state.players[1].hero_id,player=2)
                    self.play(g,'CS2_120',player=2);self.assertEqual(g.state.players[2].mana,0);g.apply(EndTurn(2))
                    self.assertEqual(len(g.state.card_summon_history),1);self.assertEqual(g.state.active_player,1)
                    self.assertEqual(g.state.players[1].secrets,[])
                saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)


@lru_cache(None)
def host_format():return build_cn37_local_pool_format()


if __name__=='__main__':unittest.main()
