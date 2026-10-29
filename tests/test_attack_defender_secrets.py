"""Original attacked residents and actual attributed random defender entries."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import attack_defender_secrets as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Destroy,ForceAttack,GainArmor,InvokeBehavior,RandomDamage,
    RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,SummonQuantitySpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,SummonFromPool
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summoned_attack_targets import TransformAttackedMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.local_pool_format import build_cn37_local_pool_format

BAMBOOZLE,MONSTER=native.LEAVES
P='k641.'
A,DEF,FIVE,SIX,THREE,OTHER,SLEEP3,SLEEP5,WATCH,DOUBLE,AXE,FAIL=(P+x for x in
    ('attacker','defender','five','six','three','other','sleep3','sleep5','watch','double','axe','fail'))
CTX=GenerationContext('k641-complete-explicit-diagnostic-domain','experimental')
PAUSE,PAUSE_MONSTER=P+'paused',P+'paused_monster'


def prompt(c):
    return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
        ChoiceOption('fill','Fill board',(Summon(c.player_id,DEF),)*7),
        ChoiceOption('allocate','Allocate an earlier same-name minion',(Summon(c.player_id,THREE),)),
        ChoiceOption('fail','Fail',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),
            InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id)


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_attack_defender_secrets(r)
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K641 deliberate original defender rollback')))
    r.register_behavior(FIVE,lambda c:(GainArmor(c.player_id,99),))
    for cid,cost,attack,health,extra in (
        (A,2,3,9,{'keywords':(Keyword.CHARGE,)}),(DEF,2,1,5,{}),(FIVE,5,6,8,{'battlecry':FIVE}),
        (SIX,6,5,10,{}),(THREE,3,2,6,{}),(OTHER,3,4,8,{}),
        (SLEEP3,3,3,4,{'dormant_turns':3}),(SLEEP5,5,3,4,{'dormant_turns':3})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=metadata(tribes=()),**extra))
    r.register_card(CardDefinition(AXE,AXE,CardType.WEAPON,attack=3,durability=3,metadata=metadata()))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=10,summon_quantities=(SummonQuantitySpec(),),metadata=metadata(tribes=())))
    def watch(c):
        event=c.event;entity=c.state.entities.get(event.source_id)
        if mode in ('reveal_transform','reveal_bounce','reveal_transfer') and event.kind=='secret_revealed' and entity is not None and entity.card_id==BAMBOOZLE:
            window=next(w for w in c.state.action_windows if w.kind=='attack')
            if mode=='reveal_transform':return (Transform(window.target_id,THREE),)
            if mode=='reveal_bounce':return (ReturnToHand(window.target_id),)
            return (ChangeControl(window.target_id,2),)
        if mode=='reveal_wait' and event.kind=='secret_revealed' and entity is not None and entity.card_id in native.LEAVES:return (prompt(c),)
        if event.kind!='minion_summoned' or entity is None or entity.card_id not in (THREE,OTHER,SLEEP3):return ()
        if mode=='entry_death':return (Destroy(entity.id,c.source_id),)
        if mode=='entry_wait':return (prompt(c),)
        if mode=='entry_fail':return (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        return ()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('minion_summoned',WATCH),TriggerSpec('secret_revealed',WATCH))))
    members=[PoolMember(SLEEP5 if mode=='sleep_transform' else FIVE),PoolMember(SIX)]
    if mode not in ('empty','unknown'):members.append(PoolMember(SLEEP3 if mode=='sleep_summon' else THREE,2))
    if mode=='weighted':members.append(PoolMember(OTHER,5))
    for cid in {x.card_id for x in members}:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='unknown':
        unknown=CardDefinition(P+'unknown',P+'unknown',CardType.MINION,cost=3,attack=2,health=6,metadata=metadata(tribes=()))
        r.register_pool_card(PoolCard.from_definition(unknown));members.append(PoolMember(unknown.id))
    r.register_pool(PoolDefinition('constructed.cards','k641-complete-fixture-'+mode,CTX.target_id,CTX.mode,tuple(members),complete=True))
    for cid,real in ((PAUSE,BAMBOOZLE),(PAUSE_MONSTER,MONSTER)):
        def paused(c,real=real):
            window,target=native.pending(c,real)
            effect=(TransformAttackedMinion(window,SourceAllocationFact.capture(c.state,c.source),SourceAllocationFact.capture(c.state,target)) if real==BAMBOOZLE else
                SummonFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=3,max_cost=3),
                    source_id=c.source_id,cause=SummonCause.capture(c),attack_window=window))
            return (prompt(c),effect)
        r.register_behavior(cid,paused);r.register_secret_condition(cid,lambda c,real=real:native.pending(c,real) is not None)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,keywords=(Keyword.SECRET,),secret=SecretSpec(cid,('attack_declared',),cid,cid),metadata=metadata()))
    r.register_behavior(P+'friendly_force',lambda c:(ForceAttack(
        next(i for i in c.state.players[1].board if c.state.entities[i].card_id==A),
        next(i for i in c.state.players[1].board if c.state.entities[i].card_id==DEF),combat_relation='friendly_minions'),))
    r.register_card(CardDefinition(P+'friendly_force',P+'friendly_force',CardType.SPELL,on_play=P+'friendly_force',metadata=metadata()))
    return r


class AttackDefenderSecretTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,secret=MONSTER,*,board=(),enemy=(A,),mode='normal',weapon=None,seed=641,context=CTX,hand=()):
        self.mode=mode
        g=Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=(secret,),board=board,deck=(DEF,)*15,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=hand,board=enemy,deck=(DEF,)*15,mana=10,max_mana=10,weapon_card_id=weapon)),seed=seed,generation_context=context),registry(mode))
        self.play(g,secret);g.apply(EndTurn(1));return g
    def attack(self,g,*,target=None,hero=False):
        source=g.state.players[2].hero_id if hero else self.entity(g,A,2,'board').id
        g.apply(Attack(2,source,target or g.state.players[1].hero_id));return source
    def row(self,g):return g.state.character_attack_history[-1]
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')});return s

    def test_complete_roots_and_four_primary_faces(self):
        data=native.load_batch();self.assertEqual([x['record']['id']for x in data['dependencies']],list(native.LEAVES))
        self.assertEqual({(x['card_id'],x['locale'])for x in data['official_observations']},{(cid,loc)for cid in native.LEAVES for loc in ('zh_CN','en_US')})
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_bamboozle_transforms_same_defender_to_full_cost_plus_three_without_battlecry(self):
        g=self.game(BAMBOOZLE,board=(DEF,));d=self.entity(g,DEF,1,'board');presence=d.board_presence_id;a=self.attack(g,target=d.id)
        result=g.state.entities[d.id];row=self.row(g)
        self.assertEqual(result.card_id,FIVE);self.assertEqual(result.board_presence_id,presence)
        self.assertEqual((result.health,g.state.entities[a].health),(5,3));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.assertEqual(row.declaration.target_id,row.delivery.target_id);self.assertEqual(g.state.entities[a].attacks_this_turn,1)
        self.assertEqual(row.terminal.status,'completed');self.assertEqual(g.state.players[1].secrets,[])

    def test_monster_true_first_delivery_becomes_same_original_attack_defender(self):
        g=self.game();a=self.attack(g);root=g.state.card_summon_history[-1];target=root.deliveries[0].entity.entity_id;row=self.row(g)
        self.assertEqual(root.request.pool_basis.attack_window,row.declaration)
        self.assertEqual(row.delivery.target_id,target);self.assertEqual(g.state.entities[target].card_id,THREE)
        self.assertEqual((g.state.entities[target].health,g.state.entities[a].health),(3,7))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30);self.assertEqual(g.state.entities[a].attacks_this_turn,1)

    def test_entry_death_cancels_attack_to_actual_dead_defender_without_hitting_hero(self):
        g=self.game(board=(WATCH,),mode='entry_death');self.attack(g);row=self.row(g)
        root=g.state.card_summon_history[-1];ident=root.deliveries[0].entity.entity_id
        self.assertEqual(row.delivery.target_id,ident);self.assertEqual(g.state.entities[ident].zone,Zone.GRAVEYARD)
        self.assertEqual(row.terminal.status,'cancelled');self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_quantity_reuses_one_selected_material_and_only_first_main_body_owns_target(self):
        g=self.game(board=(DOUBLE,));self.attack(g);root=g.state.card_summon_history[-1]
        self.assertEqual(root.plan.total,2);self.assertEqual(len(root.deliveries),2)
        first,second=(g.state.entities[x.entity.entity_id]for x in root.deliveries)
        self.assertEqual((first.card_id,second.card_id),(THREE,THREE));self.assertNotEqual(first.id,second.id)
        self.assertEqual(self.row(g).delivery.target_id,first.id);self.assertEqual((first.health,second.health),(3,6))

    def test_hero_attack_uses_actual_new_defender_and_one_original_weapon_wear(self):
        g=self.game(weapon=AXE);h=self.attack(g,hero=True)
        self.assertEqual(g.state.entities[g.state.players[2].weapon_id].durability,2)
        self.assertEqual(g.state.entities[h].health,28);self.assertEqual(g.state.hero_attack_history[0].terminal.outcome,'completed')

    def test_bamboozle_works_on_a_full_friendly_board(self):
        g=self.game(BAMBOOZLE,board=(DEF,)*7);target=g.state.players[1].board[0];self.attack(g,target=target)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.entities[target].card_id,FIVE)

    def test_bamboozle_qualifies_friendly_forced_combat_during_opponent_turn(self):
        g=self.game(BAMBOOZLE,board=(A,DEF),enemy=(),hand=(P+'friendly_force',));d=self.entity(g,DEF,1,'board').id
        self.play(g,P+'friendly_force',player=2);row=self.row(g)
        self.assertEqual(g.state.entities[d].card_id,FIVE);self.assertTrue(row.delivery.forced)
        self.assertEqual(row.delivery.combat_relation,'friendly_minions');self.assertEqual(row.terminal.status,'completed')

    def test_monster_full_board_keeps_secret_and_does_not_draw_rng(self):
        g=self.game(board=(DEF,)*7);before=g._rng.getstate();self.attack(g)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(g._rng.getstate(),before);self.assertEqual(g.state.card_summon_history,[])

    def test_empty_three_cost_domain_keeps_shared_failed_delivery_without_replacement_draw(self):
        g=self.game(mode='empty');before=g._rng.getstate();self.attack(g)
        self.assertEqual(g.state.players[1].secrets,[]);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27);self.assertIsNone(g.state.card_summon_history[-1].selected)

    def test_dormant_generation_is_retained_with_explicit_existing_local_combat_policy(self):
        g=self.game(mode='sleep_summon');self.attack(g);root=g.state.card_summon_history[-1]
        entity=g.state.entities[root.deliveries[0].entity.entity_id];self.assertEqual(entity.card_id,SLEEP3);self.assertFalse(entity.active)
        self.assertEqual(self.row(g).delivery.target_id,g.state.players[1].hero_id);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)
        g=self.game(BAMBOOZLE,board=(DEF,),mode='sleep_transform');d=self.entity(g,DEF,1,'board').id;self.attack(g,target=d)
        self.assertEqual(g.state.entities[d].card_id,SLEEP5);self.assertEqual(self.row(g).terminal.status,'cancelled')

    def test_reveal_and_entry_wait_restore_clone_replay_then_finish_same_original_attack(self):
        for secret,mode in ((MONSTER,'reveal_wait'),(MONSTER,'entry_wait'),(BAMBOOZLE,'reveal_wait')):
            with self.subTest(secret=secret,mode=mode):
                board=(WATCH,DEF)if secret==BAMBOOZLE else(WATCH,)
                g=self.game(secret,board=board,mode=mode);target=self.entity(g,DEF,1,'board').id if secret==BAMBOOZLE else None
                self.attack(g,target=target);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
                self.choose(g);self.choose(other);self.settle(g);self.settle(other)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.row(g).terminal.status,'completed')

    def test_action_failure_restores_secret_opportunity_draw_history_and_rng(self):
        g=self.game(board=(WATCH,),mode='entry_fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K641 deliberate'):self.attack(g)
        self.assertEqual(g.snapshot(),saved)

    def test_entry_choice_failure_retries_without_another_random_draw(self):
        g=self.game(board=(WATCH,),mode='entry_wait');self.attack(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K641 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.settle(g);self.assertEqual(self.row(g).terminal.status,'completed')

    def test_full_weighted_candidates_are_retained_in_original_pool_basis(self):
        g=self.game(mode='weighted');self.attack(g);basis=g.state.card_summon_history[-1].request.pool_basis
        self.assertEqual({x.card_id:x.weight for x in basis.candidates},{THREE:2,OTHER:5});self.assertEqual(len(basis.candidates),2)

    def test_reveal_transform_uses_same_original_residence_and_current_new_cost(self):
        g=self.game(BAMBOOZLE,board=(WATCH,DEF),mode='reveal_transform');d=self.entity(g,DEF,1,'board');self.attack(g,target=d.id)
        self.assertEqual(g.state.entities[d.id].card_id,SIX);self.assertEqual(g.state.entities[d.id].board_presence_id,d.board_presence_id)
        self.assertEqual(g.state.entities[d.id].health,7);self.portable(g)

    def test_departed_original_receiver_does_not_transform_its_hand_residence_or_draw_rng(self):
        g=self.game(BAMBOOZLE,board=(WATCH,DEF),mode='reveal_bounce');d=self.entity(g,DEF,1,'board').id;before=g._rng.getstate();self.attack(g,target=d)
        self.assertEqual((g.state.entities[d].zone,g.state.entities[d].card_id),(Zone.HAND,DEF))
        self.assertEqual(self.row(g).terminal.status,'cancelled');self.assertEqual(g._rng.getstate(),before)

    def test_original_receiver_transferred_after_reveal_still_gets_transformed_then_combat_cancels(self):
        g=self.game(BAMBOOZLE,board=(WATCH,DEF),mode='reveal_transfer');d=self.entity(g,DEF,1,'board').id;self.attack(g,target=d)
        self.assertEqual((g.state.entities[d].controller,g.state.entities[d].card_id),(2,FIVE))
        self.assertEqual(self.row(g).terminal.status,'cancelled');self.portable(g)

    def test_reveal_wait_then_full_board_consumes_secret_without_pool_draw_or_new_target(self):
        g=self.game(board=(WATCH,),mode='reveal_wait');before=g._rng.getstate();self.attack(g);self.choose(g,'fill');self.settle(g)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.players[1].secrets,[])
        self.assertEqual(g._rng.getstate(),before);self.assertEqual(self.row(g).delivery.target_id,g.state.players[1].hero_id)

    def test_unknown_complete_candidate_is_not_removed_or_rerolled(self):
        g=self.game(mode='unknown');saved=g.snapshot()
        with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):self.attack(g)
        self.assertEqual(g.snapshot(),saved)

    def test_missing_binding_is_explicit_and_rolls_back_original_attack(self):
        for secret in native.LEAVES:
            with self.subTest(secret=secret):
                g=self.game(secret,board=(DEF,),context=None);saved=g.snapshot();target=self.entity(g,DEF,1,'board').id if secret==BAMBOOZLE else None
                with self.assertRaisesRegex(ResolutionError,'context'):self.attack(g,target=target)
                self.assertEqual(g.snapshot(),saved)

    def test_pending_original_defender_rejects_rehashed_wrong_window_or_future_material(self):
        g=self.game(PAUSE,board=(DEF,));self.attack(g,target=self.entity(g,DEF,1,'board').id);self.portable(g);base=g.snapshot()
        def find(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.TransformAttackedMinion'):return v['fields']
                for x in v.values():
                    found=find(x)
                    if found is not None:return found
            elif isinstance(v,list):
                for x in v:
                    found=find(x)
                    if found is not None:return found
        for field in ('window','presence','source','target'):
            with self.subTest(field=field):
                saved=json.loads(json.dumps(base));row=find(saved['resolution_frame']);self.assertIsNotNone(row)
                if field=='window':row['window']['fields']['id']+=999
                elif field=='presence':row['window']['fields']['attack_target_presence']['fields']['presence_id']+=999999
                else:row[field]['fields']['next_order']+=999999
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry(self.mode))

    def test_pending_pool_defender_request_survives_allocation_after_wait_without_rebinding(self):
        g=self.game(PAUSE_MONSTER);self.attack(g);other=self.portable(g)
        self.choose(g,'allocate');self.choose(other,'allocate');self.settle(g);self.settle(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.row(g).delivery.target_id,g.state.card_summon_history[-1].deliveries[0].entity.entity_id)
        self.assertNotEqual(self.row(g).delivery.target_id,g.state.players[1].board[0])

    def test_closed_pool_basis_cannot_borrow_another_original_attack(self):
        g=self.game();self.attack(g);saved=json.loads(json.dumps(g.snapshot()))
        saved['state']['card_summon_history'][-1]['request']['pool_basis']['attack_window']['id']+=999
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_original_window_and_full_pool_material_are_not_player_information(self):
        g=self.game(board=(WATCH,),mode='entry_wait');self.attack(g);saved=g.snapshot()
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe())
            for key in ('attack_window','pool_basis','card_summon_history','resolution_frame','rng_state','window_id'):
                self.assertNotIn('"'+key+'"',view)
        self.assertEqual(g.snapshot(),saved)

    def test_bound_host_actual_defender_secrets_execute_and_restore(self):
        fmt=host_format()
        for secret in native.LEAVES:
            with self.subTest(secret=secret):
                g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(secret,),board=('CS2_120',),deck=('CS2_120',),mana=10,max_mana=10),
                    PlayerSetup('HERO_08',board=('CS2_120',),deck=('CS2_120',),mana=10,max_mana=10)),seed=641,generation_context=fmt.context),fmt.registry)
                self.play(g,secret);g.apply(EndTurn(1));source=g.state.players[2].board[0]
                target=g.state.players[1].board[0] if secret==BAMBOOZLE else g.state.players[1].hero_id
                g.apply(Attack(2,source,target));row=self.row(g);self.assertEqual(g.state.players[1].secrets,[])
                self.assertEqual(g.state.entities[source].attacks_this_turn,1)
                if secret==BAMBOOZLE:self.assertEqual(row.delivery.target_id,target)
                else:self.assertEqual(row.delivery.target_id,g.state.card_summon_history[-1].deliveries[0].entity.entity_id)
                saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)


@lru_cache(None)
def host_format():return build_cn37_local_pool_format()

if __name__=='__main__':unittest.main()
