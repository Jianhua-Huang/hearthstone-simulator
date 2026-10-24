"""Real Repair Bot and immutable consumed Magnetic material, through real actions."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_stored_carrier_materials_cards import (
    BODY, REPAIR, load_batch, register_past_stored_carrier_materials_cards)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Registry, Scenario, SnapshotError, TargetSpec,
    TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    Draw, GainArmor, InvokeBehavior, RemoveEnchantment, RequestChoice, ReturnToHand,
    Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.magnetic import ReturnMagnetizedMechs
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from tools import card_batch as batch

P='k492.'
HERO,POWER,A,M1,M2,NONMECH,WATCH=(P+x for x in
    ('hero','power','a','magnetic1','magnetic2','nonmech','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
MECH=replace(META,tribes=('mech',))


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_past_stored_carrier_materials_cards(r)
    r.register_behavior(P+'empty',lambda c:())
    r.register_behavior(P+'armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,
        initial_hero_power=POWER,metadata=META))
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'empty',metadata=META))
    r.register_card(CardDefinition(A,A,CardType.MINION,attack=1,health=10,metadata=META))
    r.register_card(CardDefinition(M1,M1,CardType.MINION,cost=2,attack=2,health=3,
        keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),deathrattle=P+'armor',metadata=MECH))
    r.register_card(CardDefinition(M2,M2,CardType.MINION,cost=1,attack=1,health=2,
        keywords=(Keyword.MAGNETIC,Keyword.DIVINE_SHIELD),magnetic_tribes=('mech',),metadata=MECH))
    r.register_card(CardDefinition(NONMECH,NONMECH,CardType.MINION,attack=1,health=2,
        keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),metadata=replace(META,tribes=('beast',))))
    def fail(c):raise ResolutionError('K492 deliberate late return failure')
    r.register_behavior(P+'fail',fail)
    targeted=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),
        trigger=lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        twice=lambda c:(TriggerDeathrattles(c.target_id,c.source_id,2),),
        silence=lambda c:(Silence(c.target_id),),bounce=lambda c:(ReturnToHand(c.target_id),),
        transform=lambda c:(Transform(c.target_id,A),),
        give=lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),),
        base=lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        remove=lambda c:(RemoveEnchantment(c.target_id,next(e.id for e in
            c.state.entities[c.target_id].enchantments if e.magnetic_id is not None)),))
    for key,body in targeted.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    def buff(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id==M1)
        return(BuffStoredCard(CardReference.capture(source),4,5,c.source_id),)
    for key,body in dict(buff=buff,
            draw=lambda c:(Draw(c.player_id,3,c.source_id),)).items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META))
    if mode=='before_return_wait':
        original=r._behaviors.pop(BODY)
        def wrapped(c):
            accepted=original(c)
            options=[ChoiceOption('continue','Continue')]
            if c.death is None:
                options.extend((ChoiceOption('silence','Silence current',(Silence(c.source_id),)),
                    ChoiceOption('transform','Transform current',(Transform(c.source_id,A),))))
            return(RequestChoice(c.player_id,tuple(options),c.source_id),*accepted)
        r.register_behavior(BODY,wrapped)
    def watch(c):
        event=c.event;target=c.state.entities.get(event.target_id)
        if (mode not in('return_wait','return_fail')or target.card_id not in(M1,M2)or
                event.source_id is None or c.state.entities[event.source_id].card_id!=REPAIR):return ()
        if mode=='return_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('card_added_to_hand',WATCH),)))
    r.validate();return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return saved


class PastStoredCarrierMaterialTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(REPAIR,),enemy=(),enemy_hand=(),mode='normal',max_hand=40):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=tuple(hand),board=tuple(board),deck=(A,)*20,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup(HERO,hand=tuple(enemy_hand),board=tuple(enemy),deck=(A,)*20,
            mana=40,max_mana=40,mana_cap=40)),seed=492),fixture(mode),Ruleset(max_hand=max_hand))

    def board(self,g,cid=REPAIR,p=1):return self.entity(g,cid,p,zone='board')
    def merge(self,g,cid=M1,host=None):
        source=self.entity(g,cid);host=self.board(g).id if host is None else host
        g.apply(PlayCard(1,source.id,None,g.state.players[1].board.index(host)))
        return source.id
    def returned(self,g,source_id,p=1):
        return[g.state.entities[i]for i in g.state.players[p].hand
            if g.state.entities[i].origin_entity_id==source_id]
    def kill(self,g,host=None):self.play(g,P+'kill',self.board(g).id if host is None else host)

    def test_two_complete_sources_four_primary_faces_only_repair_is_executable(self):
        d=load_batch();rows={x['record']['id']:x['record']for x in(*d['dependencies'],*d['evidence_only'])}
        self.assertEqual(set(rows),{REPAIR,'DEEP_012'});self.assertEqual(len(d['official_observations']),4)
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertNotIn('DEEP_012',fixture().cards)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_actual_constructed_boundary_adds_exact_one_definition(self):
        from hs_sim.cards import build_registry
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.past_stored_carrier_materials_cards.register_past_stored_carrier_materials_cards',
            register_past_stored_carrier_materials_cards,after=True)
        self.assertEqual(len(r.cards),2693);self.assertEqual(r.card(REPAIR),fixture().card(REPAIR))
        self.assertNotIn('DEEP_012',r.cards)

    def test_paid_real_one_mana_body_has_no_early_return(self):
        g=self.game((REPAIR,),board=());source=self.play(g,REPAIR)
        self.assertEqual((g.state.players[1].mana,self.board(g).attack,self.board(g).max_health),(39,1,3))
        self.assertEqual(self.board(g).id,source);self.assertFalse(g.state.deathrattle_history)

    def test_single_consumed_material_returns_fresh_base_and_original_native_body(self):
        g=self.game((M1,P+'kill'));source=self.merge(g);host=self.board(g).id
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.kill(g);copies=self.returned(g,source);self.assertEqual(len(copies),1);card=copies[0]
        self.assertEqual((card.card_id,card.attack,card.max_health,card.controller),(M1,2,3,1))
        self.assertNotEqual(card.id,source);self.assertTrue(any(a.kind=='deathrattle'for a in card.abilities))
        self.assertIn(Keyword.MAGNETIC,card.keywords);self.assertEqual(g.state.death_history[0].entity_id,host)
        self.assertEqual(g.state.magnetic_history[0].source_material.origin.entity_id,source);self.portable(g)

    def test_two_components_return_in_merge_order_with_independent_originals(self):
        g=self.game((M1,M2,P+'kill'));sources=(self.merge(g,M1),self.merge(g,M2));self.kill(g)
        self.assertEqual([g.state.entities[i].origin_entity_id for i in g.state.players[1].hand],list(sources))
        self.assertIn(Keyword.DIVINE_SHIELD,self.returned(g,sources[1])[0].keywords);self.portable(g)

    def test_duplicate_physical_components_are_not_deduplicated_by_card_id(self):
        g=self.game((M1,M1,P+'kill'));sources=(self.merge(g),self.merge(g));self.kill(g)
        self.assertNotEqual(*sources);self.assertEqual([len(self.returned(g,i))for i in sources],[1,1])

    def test_empty_components_do_not_allocate_cards_or_consume_random(self):
        g=self.game((P+'kill',));before=g.snapshot();self.kill(g)
        self.assertEqual(g.state.next_entity_id,before['state']['next_entity_id'])
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])
        self.assertEqual(g.state.players[1].hand,[]);self.portable(g)

    def test_active_trigger_returns_while_host_lives_without_fabricating_death(self):
        g=self.game((M1,P+'trigger'));source=self.merge(g);host=self.board(g).id
        self.play(g,P+'trigger',host);self.assertEqual(len(self.returned(g,source)),1)
        self.assertEqual(self.board(g).id,host);self.assertFalse(g.state.death_history);self.portable(g)

    def test_separate_active_invocations_each_return_original_components(self):
        g=self.game((M1,P+'trigger',P+'trigger'));source=self.merge(g)
        self.play(g,P+'trigger',self.board(g).id);self.play(g,P+'trigger',self.board(g).id)
        self.assertEqual(len(self.returned(g,source)),2);self.assertFalse(g.state.death_history)

    def test_fixed_trigger_rounds_use_original_components_each_round(self):
        g=self.game((M1,M2,P+'twice'));sources=(self.merge(g),self.merge(g,M2))
        self.play(g,P+'twice',self.board(g).id)
        self.assertEqual([len(self.returned(g,i))for i in sources],[2,2]);self.portable(g)

    def test_current_host_copy_retains_groups_but_base_host_copy_does_not(self):
        for spell,expected in(('copy',1),('base',0)):
            with self.subTest(spell=spell):
                g=self.game((M1,P+spell,P+'kill',P+'kill'));source=self.merge(g);host=self.board(g).id
                self.play(g,P+spell,host);copy=g.state.players[1].board[-1]
                self.kill(g,copy);self.assertEqual(len(self.returned(g,source)),expected)
                self.kill(g,host);self.assertEqual(len(self.returned(g,source)),expected+1)
                if spell=='copy':self.portable(g)

    def test_silence_and_transform_remove_return_program_and_component_groups(self):
        for spell in('silence','transform'):
            with self.subTest(spell=spell):
                g=self.game((M1,P+spell,P+'kill'));source=self.merge(g);host=self.board(g).id
                self.play(g,P+spell,host);self.kill(g,host);self.assertFalse(self.returned(g,source))

    def test_bounce_resets_groups_before_replaying_host(self):
        g=self.game((M1,P+'bounce',P+'kill'));source=self.merge(g);host=self.board(g).id
        self.play(g,P+'bounce',host);self.play(g,REPAIR);self.kill(g)
        self.assertFalse(self.returned(g,source));self.portable(g)

    def test_removing_one_group_does_not_return_removed_material(self):
        g=self.game((M1,M2,P+'remove',P+'kill'));first=self.merge(g);second=self.merge(g,M2)
        self.play(g,P+'remove',self.board(g).id);self.kill(g)
        self.assertFalse(self.returned(g,first));self.assertEqual(len(self.returned(g,second)),1)

    def test_original_hand_buff_is_recorded_but_ordinary_hand_reset_removes_it(self):
        g=self.game((M1,P+'buff',P+'kill'));self.play(g,P+'buff');source=self.merge(g)
        self.assertEqual((self.board(g).attack,self.board(g).max_health),(7,11))
        material=g.state.magnetic_history[0].source_material
        self.assertTrue(material.local.enchantments);self.kill(g);copy=self.returned(g,source)[0]
        self.assertEqual((copy.attack,copy.max_health),(2,3));self.assertFalse(copy.enchantments);self.portable(g)

    def test_returned_component_can_magnetize_again_with_a_new_physical_recipe(self):
        g=self.game((M1,P+'kill',P+'kill'),board=(REPAIR,REPAIR))
        source=self.merge(g);original=g.state.magnetic_history[0].source_material
        self.kill(g);returned=self.returned(g,source)[0].id
        self.merge(g);self.assertEqual(g.state.magnetic_history[1].source_id,returned)
        self.kill(g);self.assertFalse(self.returned(g,source))
        self.assertEqual([c.card_id for c in self.returned(g,returned)],[M1])
        self.assertEqual(g.state.magnetic_history[0].source_material,original);self.portable(g)

    def test_current_controller_receives_return_even_if_material_was_owned_by_opponent(self):
        g=self.game((M1,P+'give'),enemy_hand=(P+'kill',));source=self.merge(g);host=self.board(g).id
        self.play(g,P+'give',host);g.apply(EndTurn(1));self.play(g,P+'kill',host,player=2)
        self.assertFalse(self.returned(g,source));self.assertEqual(len(self.returned(g,source,2)),1)
        self.assertEqual(self.returned(g,source,2)[0].owner,2);self.portable(g)

    def test_only_selected_hosts_current_groups_are_returned(self):
        g=self.game((M1,M2,P+'kill'),board=(REPAIR,REPAIR));hosts=tuple(g.state.players[1].board)
        first=self.merge(g,M1,hosts[0]);second=self.merge(g,M2,hosts[1]);self.kill(g,hosts[0])
        self.assertEqual(len(self.returned(g,first)),1);self.assertFalse(self.returned(g,second))

    def test_non_mech_magnetic_material_is_excluded_by_the_actual_text(self):
        g=self.game((NONMECH,M2,P+'kill'));a=self.merge(g,NONMECH);b=self.merge(g,M2);self.kill(g)
        self.assertFalse(self.returned(g,a));self.assertEqual(len(self.returned(g,b)),1)

    def test_full_hand_uses_normal_order_and_created_overflow(self):
        g=self.game((M1,M2,P+'draw',P+'kill'),max_hand=4)
        first=self.merge(g);second=self.merge(g,M2);self.play(g,P+'draw');self.kill(g)
        self.assertEqual(len(g.state.players[1].hand),4);self.assertEqual(len(self.returned(g,first)),1)
        self.assertFalse(self.returned(g,second));burns=[e for e in g.events if e.kind=='card_burned']
        self.assertEqual(len(burns),1);burned=g.state.entities[burns[0].target_id]
        self.assertEqual((burned.card_id,burned.origin_entity_id,burned.zone),(M2,second,Zone.GRAVEYARD));self.portable(g)

    def test_waiting_between_deliveries_restores_replays_and_resumes_once(self):
        g=self.game((M1,M2,P+'kill'),board=(REPAIR,WATCH),mode='return_wait')
        sources=(self.merge(g),self.merge(g,M2));self.kill(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual([len(self.returned(g,i))for i in sources],[1,0])
        other=self.portable(g)
        for live in(g,other):self.choose(live);self.assertIsNotNone(live.state.pending_choice);self.choose(live)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([len(self.returned(g,i))for i in sources],[1,1])
        self.portable(g)

    def test_failing_choice_preserves_waiting_accepted_delivery(self):
        g=self.game((M1,P+'kill'),board=(REPAIR,WATCH),mode='return_wait');self.merge(g);self.kill(g)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertIsNone(g.state.pending_choice)

    def test_late_return_failure_rolls_back_original_kill_and_all_deliveries(self):
        g=self.game((M1,M2,P+'kill'),board=(REPAIR,WATCH),mode='return_fail');self.merge(g);self.merge(g,M2)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.kill(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_accepted_active_return_keeps_original_groups_after_host_silence(self):
        g=self.game((M1,P+'trigger'),mode='before_return_wait');source=self.merge(g)
        self.play(g,P+'trigger',self.board(g).id)
        self.assertIn('ReturnMagnetizedMechs',json.dumps(g.snapshot()['resolution_frame']))
        other=self.portable(g)
        for live in(g,other):self.choose(live,'silence');self.assertEqual(len(self.returned(live,source)),1)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_natural_request_rejects_missing_original_group_while_queued(self):
        g=self.game((M1,P+'kill'),mode='before_return_wait');self.merge(g);self.kill(g)
        row=next(x for x in g.state.deathrattle_history if x.capture.ability.behavior_id==BODY)
        with self.assertRaises(ValueError):ReturnMagnetizedMechs(row.id,()).validate_in_state(g.state)
        self.portable(g);self.choose(g);self.portable(g)

    def test_later_trigger_round_reads_new_transformed_carrier_without_old_groups(self):
        g=self.game((M1,P+'twice'),mode='before_return_wait');source=self.merge(g);host=self.board(g).id
        self.play(g,P+'twice',host);self.choose(g,'transform')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[host].card_id,A)
        other=self.portable(g)
        for live in(g,other):self.choose(live);self.assertEqual(len(self.returned(live,source)),1)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_rehashed_consumed_material_none_source_and_future_bounds_are_rejected(self):
        g=self.game((M1,));self.merge(g);original=g.snapshot()
        for kind in('missing','other_source','future'):
            bad=deepcopy(original);row=bad['state']['magnetic_history'][0]
            if kind=='missing':row['source_material']=None
            elif kind=='other_source':row['source_material']['origin']['entity_id']=self.board(g).id
            else:row['source_material']['action']=g.state.action_number+1
            with self.subTest(kind=kind),self.assertRaises(SnapshotError)as caught:
                Game.from_snapshot(rehash(bad),fixture('normal','forged-reader'))
            self.assertNotIn('digest mismatch',str(caught.exception))
        self.portable(g)

    def test_active_request_rejects_missing_or_other_carrier_material(self):
        g=self.game((M1,P+'trigger'),mode='before_return_wait');self.merge(g)
        self.play(g,P+'trigger',self.board(g).id)
        row=next(x for x in g.state.deathrattle_history if x.capture.ability.behavior_id==BODY)
        with self.assertRaises(ValueError):ReturnMagnetizedMechs(row.id,(1,)).validate_in_state(g.state)
        with self.assertRaises(ValueError):ReturnMagnetizedMechs(0,(1,))
        with self.assertRaises(ValueError):ReturnMagnetizedMechs(row.id,(1,1))
        self.choose(g);self.portable(g)
