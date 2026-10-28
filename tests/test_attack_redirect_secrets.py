"""Actual Secret entries, original combat credit, complete domains and recovery."""
from dataclasses import replace
from functools import lru_cache
import json, unittest
from random import Random

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import attack_redirect_secrets as native
from hs_sim.engine import Attack, EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario, SnapshotError
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.attack_redirects import RandomRedirectAttack, pending_attack, candidates
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, ForceAttack, GainArmor, InvokeBehavior,
    RandomDamage, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, Keyword, SecretSpec, TriggerSpec, Zone
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.serialization import canonical_hash
from hs_sim.local_pool_format import build_cn37_local_pool_format

MISDIRECTION, BETRAYAL = native.LEAVES
P = 'k640.'
A, LEFT, RIGHT, FRAGILE, STEALTH, IMMUNE, SLEEP, LOCATION, WATCH, AXE, FORCE, EXCESS, FAIL, PAUSED = (
    P+x for x in ('attacker','left','right','fragile','stealth','immune','sleep','location','watch','axe','force','excess','fail','paused'))


def prompt(c):
    neighbors = [i for i in c.state.players[2].board if c.state.entities[i].card_id not in (A, WATCH)]
    remove = tuple(Destroy(i, c.source_id) for i in neighbors)
    attacker = next((i for i in c.state.players[2].board if c.state.entities[i].card_id == A), None)
    departed = () if attacker is None else (ReturnToHand(attacker),)
    target=c.state.entities.get(c.event.target_id)
    transfer=() if target is None or target.kind!=CardType.MINION else (ChangeControl(target.id,3-target.controller),)
    target_depart=() if target is None or target.kind!=CardType.MINION else (ReturnToHand(target.id),)
    return RequestChoice(c.player_id, (ChoiceOption('continue','Continue'), ChoiceOption('remove','Remove neighbors',remove),
        ChoiceOption('allocate','Allocate a new physical entity',(Summon(1,LEFT,c.source_id),)),
        ChoiceOption('depart','Return attacker',departed),
        ChoiceOption('transfer','Transfer selected minion',transfer),ChoiceOption('target_depart','Return selected target',target_depart),
        ChoiceOption('fail','Fail',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))), c.source_id)


@lru_cache(None)
def registry(mode='normal', role='writer'):
    r = opening_registry(); native.register_attack_redirect_secrets(r)
    if mode=='neptulon':
        from hs_sim.cards.simple_followup_p74_cards import register_simple_followup_p74_cards
        from hs_sim.cards.neptulon_substitution import register_neptulon_substitution
        register_simple_followup_p74_cards(r);register_neptulon_substitution(r)
    for cid, attack, health, keywords, extra in (
        (A,3,8,(Keyword.CHARGE,),{}),(LEFT,1,8,(),{}),(RIGHT,2,8,(),{}),(FRAGILE,1,1,(),{}),
        (STEALTH,2,8,(Keyword.STEALTH,),{}),(IMMUNE,2,8,(Keyword.IMMUNE,),{}),(SLEEP,2,8,(),{'dormant_turns':3})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,keywords=keywords,
            metadata=metadata(tribes=()),**extra))
    r.register_behavior(LOCATION,lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=3,on_use=LOCATION,metadata=metadata()))
    r.register_card(CardDefinition(AXE,AXE,CardType.WEAPON,attack=3,durability=3,metadata=metadata()))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K640 deliberate redirect rollback')))
    def watcher(c):
        if mode == 'normal':return ()
        if mode == 'reveal' and c.event.kind == 'secret_revealed' and c.state.entities[c.event.source_id].card_id in (*native.LEAVES,PAUSED):return (prompt(c),)
        if mode in ('redirect','finish') and c.event.kind == ('attack_redirected' if mode=='redirect' else 'attack_finished'):return (prompt(c),)
        if mode == 'fail' and c.event.kind == 'attack_redirected':return (RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        return ()
    r.register_behavior(WATCH,watcher)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=metadata(tribes=()),
        triggers=tuple(TriggerSpec(e,WATCH) for e in ('secret_revealed','attack_redirected','attack_finished'))))
    for cid, excess in ((FORCE,False),(EXCESS,True)):
        def force(c, excess=excess):
            attacker=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==A)
            return (ForceAttack(BoardPresenceReference.capture(c.state,attacker),c.state.players[3-c.player_id].hero_id,excess_to_hero=excess),)
        r.register_behavior(cid,force)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def paused(c):
        w=pending_attack(c.state,c.event,c.player_id,'attacker_neighbor')
        if w is None:return ()
        return (prompt(c),RandomRedirectAttack(w,SourceAllocationFact.capture(c.state,c.source),'attacker_neighbor'))
    r.register_secret_condition(PAUSED,lambda c:pending_attack(c.state,c.event,c.player_id,'attacker_neighbor') is not None)
    r.register_behavior(PAUSED,paused)
    r.register_card(CardDefinition(PAUSED,PAUSED,CardType.SPELL,keywords=(Keyword.SECRET,),
        secret=SecretSpec(PAUSED,('attack_declared',),PAUSED,PAUSED),metadata=metadata()))
    return r


@lru_cache(None)
def host_format():return build_cn37_local_pool_format()


class AttackRedirectSecretTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'

    def game(self, secret=MISDIRECTION, *, board=(), enemy=(A,), weapon=None, hand=(), mode='normal', seed=640, others=()):
        self.mode=mode
        g=Game.from_scenario(Scenario((
            PlayerSetup('mage.hero',hand=(secret,*others),board=board,deck=(LEFT,)*15,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=hand,board=enemy,deck=(LEFT,)*15,mana=10,max_mana=10,weapon_card_id=weapon)),seed=seed),registry(mode))
        for cid in (secret,*others):self.play(g,cid)
        g.apply(EndTurn(1));return g

    def attack(self,g,*,hero=False,target=None):
        source=g.state.players[2].hero_id if hero else self.entity(g,A,2,'board').id
        g.apply(Attack(2,source,target or g.state.players[1].hero_id));return source

    def row(self,g):return g.state.character_attack_history[-1]
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def rehash(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        return saved

    def test_complete_records_and_primary_faces(self):
        d=native.load_batch();self.assertEqual([x['record']['id'] for x in d['dependencies']],list(native.LEAVES))
        self.assertEqual({(x['card_id'],x['locale'])for x in d['official_observations']},{(cid,locale)for cid in native.LEAVES for locale in ('zh_CN','en_US')})
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        for x in d['dependencies']:
            card=registry().card(x['record']['id']);self.assertEqual(card.cost,2);self.assertEqual(card.secret.events,('attack_declared',))

    def test_misdirection_minion_hits_own_hero_and_takes_weapon_retaliation_without_wear(self):
        g=self.game(weapon=AXE);before=g._rng.getstate();a=self.attack(g);row=self.row(g)
        self.assertEqual(row.delivery.target_id,g.state.players[2].hero_id)
        self.assertEqual(row.delivery.combat_relation,'any_characters');self.assertFalse(row.delivery.forced)
        self.assertEqual(g.state.entities[a].health,5);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertEqual(g.state.entities[g.state.players[2].weapon_id].durability,3)
        self.assertEqual(g.state.entities[a].attacks_this_turn,1);self.assertEqual(len(g.state.hero_attack_history),0)
        self.assertEqual(g._rng.getstate(),before);self.assertEqual(row.terminal.status,'completed')

    def test_misdirection_hero_hits_own_minion_with_one_original_weapon_wear(self):
        g=self.game(weapon=AXE);a=self.entity(g,A,2,'board').id;h=self.attack(g,hero=True);row=self.row(g)
        self.assertEqual(row.delivery.target_id,a);self.assertEqual(g.state.entities[a].health,5)
        self.assertEqual(g.state.entities[h].health,27);self.assertEqual(g.state.entities[h].attacks_this_turn,1)
        self.assertEqual(g.state.entities[g.state.players[2].weapon_id].durability,2)
        self.assertEqual(len(g.state.hero_attack_history),1);self.assertEqual(g.state.hero_attack_history[0].terminal.outcome,'completed')
        self.assertEqual(g.state.hero_attack_history[0].delivery.combat_relation,'any_characters')
        self.portable(g)

    def test_betrayal_single_physical_neighbor_same_attack_and_no_rng(self):
        g=self.game(BETRAYAL,enemy=(A,LEFT));before=g._rng.getstate();a=self.attack(g);row=self.row(g);left=self.entity(g,LEFT,2,'board')
        self.assertEqual(row.delivery.target_id,left.id);self.assertEqual(g.state.entities[a].health,7);self.assertEqual(left.health,5)
        self.assertEqual(row.secret_redirects[0].candidates,(left.id,));self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(g.state.entities[a].attacks_this_turn,1);self.assertFalse(row.delivery.forced)

    def test_betrayal_two_neighbor_domain_keeps_order_and_samples_once(self):
        g=self.game(BETRAYAL,enemy=(LEFT,A,RIGHT));before=g._rng.getstate();self.attack(g);proof=self.row(g).secret_redirects[0]
        expected=(self.entity(g,LEFT,2,'board').id,self.entity(g,RIGHT,2,'board').id)
        self.assertEqual(proof.candidates,expected);rng=Random();rng.setstate(before)
        self.assertEqual(proof.selected_id,rng.choice(expected));self.assertEqual(proof.rng_after,rng.getstate())
        self.assertEqual(g._rng.getstate(),proof.rng_after)

    def test_betrayal_empty_and_hero_attack_keep_secret(self):
        for hero in (False,True):
            with self.subTest(hero=hero):
                g=self.game(BETRAYAL,weapon=AXE);before=g._rng.getstate();self.attack(g,hero=hero)
                self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(self.row(g).secret_redirects)
                self.assertEqual(g._rng.getstate(),before)

    def test_misdirection_hero_without_other_character_keeps_secret(self):
        g=self.game(enemy=(),weapon=AXE);before=g._rng.getstate();self.attack(g,hero=True)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(g._rng.getstate(),before)

    def test_forced_attack_preserves_forced_origin_and_no_opportunity_spend(self):
        g=self.game(BETRAYAL,enemy=(A,LEFT),hand=(FORCE,));a=self.entity(g,A,2,'board').id
        self.play(g,FORCE,player=2);row=self.row(g)
        self.assertTrue(row.declaration.forced);self.assertTrue(row.delivery.forced);self.assertEqual(g.state.entities[a].attacks_this_turn,0)
        self.assertEqual(len(g.state.character_attack_history),1)

    def test_forced_excess_policy_keeps_original_window_when_redirected_to_hero(self):
        g=self.game(hand=(EXCESS,));self.play(g,EXCESS,player=2);row=self.row(g)
        self.assertTrue(row.delivery.excess_to_hero);self.assertTrue(row.delivery.forced)
        self.assertEqual(row.delivery.target_id,g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)

    def test_dormant_and_location_slots_block_neighbors_without_bridging(self):
        for blocker in (SLEEP,LOCATION):
            with self.subTest(blocker=blocker):
                g=self.game(BETRAYAL,enemy=(LEFT,blocker,A));before=g._rng.getstate();self.attack(g)
                self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(self.row(g).secret_redirects)
                self.assertEqual(g._rng.getstate(),before);self.assertEqual(self.entity(g,LEFT,2,'board').health,8)

    def test_dormant_slot_blocks_one_side_and_live_immediate_other_side_remains(self):
        g=self.game(BETRAYAL,enemy=(LEFT,SLEEP,A,RIGHT));self.attack(g);row=self.row(g)
        self.assertEqual(row.secret_redirects[0].candidates,(self.entity(g,RIGHT,2,'board').id,))
        self.assertEqual(self.entity(g,LEFT,2,'board').health,8)

    def test_misdirection_domain_includes_both_sides_and_excludes_protected_hero_attacker_and_sleep(self):
        g=self.game(board=(LEFT,),enemy=(A,STEALTH,IMMUNE,SLEEP,LOCATION));self.attack(g);proof=self.row(g).secret_redirects[0]
        expected=(self.entity(g,LEFT,1,'board').id,g.state.players[2].hero_id,
            self.entity(g,STEALTH,2,'board').id,self.entity(g,IMMUNE,2,'board').id)
        self.assertEqual(proof.candidates,expected)
        self.assertEqual([x.allocation.card_id for x in proof.boards[1]],[A,STEALTH,IMMUNE,SLEEP,LOCATION])

    def test_neighbor_replacement_can_hit_stealth_and_preserves_immune_protection_local_policy(self):
        for neighbor in (STEALTH,IMMUNE):
            with self.subTest(neighbor=neighbor):
                g=self.game(BETRAYAL,enemy=(A,neighbor));a=self.attack(g);target=self.entity(g,neighbor,2,'board')
                self.assertEqual(self.row(g).delivery.target_id,target.id)
                self.assertEqual(target.health,8 if neighbor==IMMUNE else 5);self.assertEqual(g.state.entities[a].health,6)

    def test_attacking_a_minion_keeps_both_real_secrets(self):
        for secret in native.LEAVES:
            with self.subTest(secret=secret):
                g=self.game(secret,board=(LEFT,),enemy=(A,RIGHT));target=self.entity(g,LEFT,1,'board').id
                self.attack(g,target=target);self.assertEqual(len(g.state.players[1].secrets),1)
                self.assertFalse(self.row(g).secret_redirects)

    def test_second_secret_rechecks_current_target_after_first_replacement(self):
        for first,second in ((MISDIRECTION,BETRAYAL),(BETRAYAL,MISDIRECTION)):
            with self.subTest(first=first):
                g=self.game(first,others=(second,),enemy=(A,LEFT));self.attack(g)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].secrets],[second])
                self.assertEqual(len(self.row(g).secret_redirects),1);self.assertEqual(len(g.state.character_attack_history),1)

    def test_real_wait_boundaries_restore_clone_replay_and_continue_without_reroll(self):
        for mode,secret,hero in (('reveal',BETRAYAL,False),('redirect',BETRAYAL,False),
                ('redirect',MISDIRECTION,True),('finish',MISDIRECTION,False)):
            with self.subTest(mode=mode,secret=secret,hero=hero):
                enemy=(A,LEFT) if secret==BETRAYAL else (A,)
                g=self.game(secret,board=(WATCH,),enemy=enemy,weapon=AXE if hero else None,mode=mode)
                self.attack(g,hero=hero);self.assertIsNotNone(g.state.pending_choice)
                other=self.portable(g);before=g._rng.getstate();self.choose(g);self.choose(other)
                self.settle(g);self.settle(other);self.assertEqual(g.snapshot(),other.snapshot())
                self.assertEqual(g._rng.getstate(),self.row(g).secret_redirects[-1].rng_after)
                if mode!='reveal':self.assertEqual(g._rng.getstate(),before)

    def test_reveal_wait_removing_all_neighbors_consumes_revealed_secret_without_rng(self):
        g=self.game(BETRAYAL,board=(WATCH,),enemy=(A,LEFT),mode='reveal');before=g._rng.getstate();self.attack(g)
        other=self.portable(g);self.choose(g,'remove');self.choose(other,'remove');self.settle(g);self.settle(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].secrets,[])
        self.assertFalse(self.row(g).secret_redirects);self.assertEqual(g._rng.getstate(),before)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)

    def test_redirect_wait_departed_attacker_cancels_the_same_attack(self):
        g=self.game(BETRAYAL,board=(WATCH,),enemy=(A,LEFT),mode='redirect');a=self.attack(g)
        self.choose(g,'depart');self.settle(g);row=self.row(g)
        self.assertEqual(g.state.entities[a].zone,Zone.HAND);self.assertEqual(row.terminal.status,'cancelled')
        self.assertIsNone(row.combat);self.assertEqual(self.entity(g,LEFT,2,'board').health,8)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_selected_target_control_change_keeps_the_same_residence_and_attack(self):
        g=self.game(BETRAYAL,board=(WATCH,),enemy=(A,LEFT),mode='redirect');self.attack(g)
        selected=self.row(g).secret_redirects[0].selected;self.choose(g,'transfer');self.settle(g)
        row=self.row(g);self.assertEqual(row.terminal.status,'completed')
        self.assertEqual(row.delivery.attack_target_presence,selected.presence)
        self.assertEqual(row.combat.target_player_id,1);self.assertEqual(g.state.entities[selected.allocation.entity_id].health,5)
        self.portable(g)

    def test_departed_selected_minion_cancels_hero_delivery_without_weapon_wear(self):
        g=self.game(board=(WATCH,),weapon=AXE,mode='redirect');h=self.attack(g,hero=True)
        self.choose(g,'target_depart');self.settle(g)
        self.assertEqual(self.row(g).terminal.status,'cancelled');self.assertIsNone(self.row(g).combat)
        self.assertEqual(g.state.hero_attack_history[0].terminal.outcome,'cancelled')
        self.assertEqual(g.state.entities[g.state.players[2].weapon_id].durability,3)
        self.assertEqual(g.state.entities[h].attacks_this_turn,1)

    def test_request_before_choice_keeps_original_source_after_new_allocations(self):
        g=self.game(PAUSED,enemy=(A,LEFT));self.attack(g);self.assertIsNotNone(g.state.pending_choice)
        original=self.row(g);self.assertFalse(original.secret_redirects);other=self.portable(g)
        self.choose(g,'allocate');self.choose(other,'allocate');self.settle(g);self.settle(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.row(g).delivery.target_id,self.entity(g,LEFT,2,'board').id)
        self.assertGreater(self.row(g).secret_redirects[0].source.next_entity_id,original.declaration.source_id)

    def test_pending_failure_rolls_back_choice_events_and_rng_then_retries_same_selection(self):
        g=self.game(BETRAYAL,board=(WATCH,),enemy=(LEFT,A,RIGHT),mode='redirect');self.attack(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K640 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.settle(g)
        self.assertEqual(self.row(g).terminal.status,'completed')

    def test_action_failure_rolls_back_original_opportunity_secret_and_random_draw(self):
        g=self.game(BETRAYAL,board=(WATCH,),enemy=(LEFT,A,RIGHT),mode='fail');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K640 deliberate'):self.attack(g)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.character_attack_history,[])

    def test_closed_selection_rejects_rehashed_cropped_future_and_wrong_random_facts(self):
        g=self.game(BETRAYAL,enemy=(LEFT,A,RIGHT));self.attack(g);base=g.snapshot()
        def proof(s):return s['state']['character_attack_history'][-1]['secret_redirects'][0]
        changes=(
            lambda s:proof(s).__setitem__('candidates',proof(s)['candidates'][:1]),
            lambda s:proof(s).__setitem__('selected_id',g.state.players[1].hero_id),
            lambda s:proof(s)['boards'][1].reverse(),
            lambda s:proof(s).__setitem__('rng_after',proof(s)['rng_before']),
            lambda s:proof(s)['source'].__setitem__('next_order',10**9),
            lambda s:proof(s)['boards'][1][0]['presence'].__setitem__('presence_id',10**9),
            lambda s:proof(s).__setitem__('action',10**9),
            lambda s:s['state']['character_attack_history'][-1]['secret_redirects'].append(proof(s)),
            lambda s:s['state']['character_attack_history'][-1].__setitem__('secret_redirects',[]),
        )
        for i,change in enumerate(changes):
            with self.subTest(change=i):
                saved=json.loads(json.dumps(base));change(saved)
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_pending_effect_rejects_rehashed_wrong_window_profile_or_future_source(self):
        g=self.game(PAUSED,enemy=(A,LEFT));self.attack(g);base=g.snapshot()
        def find(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.RandomRedirectAttack'):return v['fields']
                for x in v.values():
                    result=find(x)
                    if result is not None:return result
            elif isinstance(v,list):
                for x in v:
                    result=find(x)
                    if result is not None:return result
        for kind in ('window','profile','future'):
            with self.subTest(kind=kind):
                saved=json.loads(json.dumps(base));fields=find(saved['resolution_frame']);self.assertIsNotNone(fields)
                if kind=='window':fields['window']['fields']['id']+=999
                elif kind=='profile':fields['profile']='invented-combination'
                else:fields['source']['fields']['next_entity_id']=10**9
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_redirect_event_requires_its_original_complete_private_receipt(self):
        g=self.game(BETRAYAL,enemy=(LEFT,A,RIGHT));self.attack(g);base=g.snapshot()
        for mode in ('remove','wrong','relation'):
            with self.subTest(mode=mode):
                saved=json.loads(json.dumps(base))
                if mode=='relation':saved['state']['character_attack_history'][-1]['delivery']['combat_relation']='opponent'
                else:
                    event=next(e for e in saved['events'] if e['kind']=='attack_redirected')
                    if mode=='remove':event['data'].pop('_secret_redirect_receipt')
                    else:event['data']['_secret_redirect_receipt']='{}'
                with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_same_epoch_source_face_cannot_be_rewritten_even_with_matching_private_receipt(self):
        from hs_sim.engine.attack_redirects import encoded,selection_from_dict
        g=self.game(BETRAYAL,enemy=(A,LEFT));self.attack(g);saved=json.loads(json.dumps(g.snapshot()))
        proof=saved['state']['character_attack_history'][-1]['secret_redirects'][0]
        proof['source']['card_id']=MISDIRECTION
        event=next(e for e in saved['events'] if e['kind']=='attack_redirected')
        event['data']['_secret_redirect_receipt']=encoded(selection_from_dict(proof))
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(saved),registry())

    def test_complete_proof_never_enters_player_information(self):
        g=self.game(BETRAYAL,board=(WATCH,),enemy=(LEFT,A,RIGHT),mode='redirect');self.attack(g);saved=g.snapshot()
        self.assertIn('_secret_redirect_receipt',json.dumps(saved));self.assertEqual(len(self.row(g).secret_redirects),1)
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe())
            for key in ('secret_redirects','_secret_redirect_receipt','candidates','rng_before','rng_after','board_presence_id','window_id'):
                self.assertNotIn('"'+key+'"',view)
        self.assertEqual(g.snapshot(),saved)

    def test_bare_new_combat_or_new_force_cannot_impersonate_redirected_delivery(self):
        with self.assertRaises(ValueError):CombatDamage(1,2,combat_relation='any_characters')
        with self.assertRaises(ValueError):ForceAttack(1,2,combat_relation='any_characters')

    def test_bound_host_two_actual_secrets_execute_and_restore_with_independent_registry(self):
        fmt=host_format()
        for secret in native.LEAVES:
            with self.subTest(secret=secret):
                g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(secret,),deck=('CS2_120',),mana=10,max_mana=10),
                    PlayerSetup('HERO_08',board=('CS2_120','CS2_120'),deck=('CS2_120',),mana=10,max_mana=10)),
                    seed=640,generation_context=fmt.context),fmt.registry)
                self.play(g,secret);g.apply(EndTurn(1));a=g.state.players[2].board[0]
                g.apply(Attack(2,a,g.state.players[1].hero_id));row=self.row(g)
                self.assertEqual(len(row.secret_redirects),1);self.assertEqual(row.terminal.status,'completed')
                self.assertEqual(g.state.entities[a].attacks_this_turn,1)
                saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)

    def test_real_neptulon_keeps_already_accepted_member_plan_through_secret_redirection(self):
        from hs_sim.cards.neptulon_substitution import CARD,HANDS
        g=self.game(BETRAYAL,enemy=(HANDS[0],CARD,HANDS[1]),mode='neptulon')
        parent=self.entity(g,CARD,2,'board').id;g.apply(Attack(2,parent,g.state.players[1].hero_id))
        row=next(x for x in g.state.character_attack_history if x.declaration.source_id==parent)
        self.assertIsNotNone(row.substitution);self.assertEqual(row.terminal.status,'replaced')
        self.assertEqual(row.substitution.status,'completed');self.assertIsNone(row.combat)
        self.assertEqual(len([x for x in g.state.character_attack_history if x.secret_redirects]),1)
        self.assertEqual(len(row.substitution.attempts),2)
        self.portable(g)


if __name__=='__main__':unittest.main()
