"""Actual two-arrow Flame Shock under the documented local adjacent policy."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json,random,unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_conductivity import fixture as original_fixture,A,B,C,ELUSIVE,SD
from hs_sim.cards import past_conductivity as native
from hs_sim.engine import Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,GrantKeyword,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand,Summon)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TriggerSpec,Zone
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARD=native.ROOTS[0];BE='BE_302';P='k680.';D=P+'d';E=P+'e';FAIL=P+'fail';SET=P+'set'


def watcher(mode):return P+'watch.'+mode
def driver(mode):return P+'auto.'+mode


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=original_fixture.__wrapped__(role)
    for cid in(D,E):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=20,metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K680 deliberate grouped body rollback')))
    def menu(c):
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',
            (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    def watch(c):
        cast=next((x for x in reversed(c.state.cast_history)if x.card_id==BE and x.payload_started and not x.completed and not x.interrupted),None)
        if cast is None or cast.player_id!=c.player_id:return()
        if mode=='accepted'and c.event.kind=='spell_cast_accepted'and c.event.source_id==cast.source_id:return menu(c)
        if mode=='overload'and c.event.kind=='overload_added'and c.event.player_id==c.player_id:return menu(c)
        if (c.event.kind!='damage_dealt'or c.event.source_id!=cast.source_id or c.event.target_id!=cast.target_id or
                cast.next_spell_body_cursor!=0):return()
        other=next((f for f in cast.spell_target_receipt.targets if f is not None and f.entity_id!=cast.target_id),None)
        if mode=='elusive':return(GrantKeyword(other.entity_id,Keyword.ELUSIVE,c.source_id),)
        if mode=='control':return(ChangeControl(other.entity_id,c.player_id),)
        if mode=='return_secondary':return(ReturnToHand(other.entity_id),)
        if mode=='replace_neighbor':
            board=c.state.players[3-c.player_id].board;left=board[board.index(cast.target_id)-1]
            return(ReturnToHand(left),Summon(3-c.player_id,A))
        return()
    r.register_behavior(watcher(mode),watch)
    r.register_card(CardDefinition(watcher(mode),watcher(mode),CardType.MINION,health=30,
        triggers=tuple(TriggerSpec(k,watcher(mode))for k in('damage_dealt','overload_added','spell_cast_accepted')),
        metadata=metadata(collectible=False,tribes=())))
    def auto(c):
        target=c.state.players[3-c.player_id].board[1];hero=c.state.players[3-c.player_id].hero_id
        return(CastSpell(c.player_id,BE,c.source_id),)if mode=='accepted'else(
            CastSpell(c.player_id,BE,c.source_id,targeting='explicit',target_id=target,target_ids=(target,hero)),)
    r.register_behavior(driver(mode),auto)
    r.register_card(CardDefinition(driver(mode),driver(mode),CardType.MINION,cost=1,health=4,
        on_play=driver(mode),metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(SET,lambda c:(SetSecret(3-c.player_id,'CORE_EX1_287'),))
    r.register_card(CardDefinition(SET,SET,CardType.MINION,health=4,on_play=SET,metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


def rehash(value):
    value['events_hash']=canonical_hash(value['events'])
    value['state_hash']=canonical_hash({k:v for k,v in value.items()if k not in('schema_version','events','events_hash','state_hash')})
    return value


class ConductivityGroupTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(mode,role))
    def game(self,*,mode='normal',enemy=(A,B,C),board=(),hand=(CARD,BE),active=1,seed=680):
        self.mode=mode
        if mode!='normal':board=(watcher(mode),*board)
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_08',hand=hand if p==active else(),
            board=board if p==active else enemy,deck=(A,)*8,mana=10,max_mana=10)for p in(1,2)),
            active_player=active,seed=seed),fixture(mode,'writer'))
    def ids(self,g,p=2):return tuple(g.state.players[p].board)
    def hp(self,g,ids):return tuple(g.state.entities[i].health for i in ids)
    def cast(self,g):return next(c for c in reversed(g.state.cast_history)if c.card_id==BE)
    def pair(self,g,first,second,p=1):
        eid=self.entity(g,BE,p).id;g.apply(PlayCard(p,eid,first,target_ids=(first,second)));return eid
    def start(self,g,second=None,p=1):
        ids=self.ids(g,3-p);self.play(g,CARD,player=p)
        return self.pair(g,ids[1],g.state.players[3-p].hero_id if second is None else second,p)
    def drain(self,g):
        for _ in range(8):
            if g.state.pending_choice is None:return
            self.choose(g)
        self.fail('Grouped body choices did not finish')

    def test_v3_keeps_full_original_roles_and_explicit_local_policy_evidence(self):
        d=native.load_batch();self.assertFalse(d['multi_arrow_support']['official_exact'])
        self.assertEqual(d['additional_compatibility_dependencies'][0]['record']['id'],BE)
        self.assertEqual(len(d['multi_arrow_source_observations']),2)
        self.assertEqual(len(d['original_shaman_member_ids']),71);self.assertFalse(d['complete_shaman_source_bound'])

    def test_original_pair_and_three_full_bodies_one_cost_three_overload_no_extra_rng(self):
        g=self.game();ids=self.ids(g);hero=g.state.players[2].hero_id;before=g.snapshot()['rng_state'];self.start(g)
        self.assertEqual(self.hp(g,ids),(18,18,18));self.assertEqual(g.state.entities[hero].health,24)
        self.assertEqual(g.state.players[1].overload_owed,3);self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(len(g.state.play_history),2)
        self.assertEqual(tuple(f.entity_id for f in self.cast(g).spell_target_receipt.targets),(ids[1],hero))
        self.assertEqual(self.cast(g).target_id,ids[1]);self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_secondary_minion_keeps_its_original_arrow_and_does_not_expand_its_neighbors(self):
        g=self.game(enemy=(A,B,C,D,E));ids=self.ids(g);self.start(g,ids[4])
        self.assertEqual(self.hp(g,ids),(18,18,18,20,14));self.assertEqual(g.state.players[1].overload_owed,3)
        self.portable(g)

    def test_neighbor_collision_deduplicates_execution_without_rewriting_two_inputs(self):
        g=self.game();ids=self.ids(g);self.start(g,ids[2])
        self.assertEqual(self.hp(g,ids),(18,18,14));self.assertEqual(g.state.players[1].overload_owed,3)
        self.assertEqual(self.cast(g).spell_target_group.target_ids,(ids[1],ids[2]));self.portable(g)

    def test_primary_hero_does_not_borrow_secondary_minion_adjacency(self):
        g=self.game();ids=self.ids(g);hero=g.state.players[2].hero_id;self.play(g,CARD);self.pair(g,hero,ids[1])
        self.assertEqual(self.hp(g,ids),(20,18,20));self.assertEqual(g.state.entities[hero].health,28)
        self.assertEqual(g.state.players[1].overload_owed,1);self.assertEqual(self.cast(g).next_spell_body_board,());self.portable(g)

    def test_illegal_adjacent_primary_skips_whole_group_body(self):
        g=self.game(enemy=(ELUSIVE,B,C));ids=self.ids(g);hero=g.state.players[2].hero_id;self.start(g)
        self.assertEqual(self.hp(g,ids),(20,18,18));self.assertEqual(g.state.entities[hero].health,26)
        self.assertEqual(g.state.players[1].overload_owed,2);self.portable(g)

    def test_secondary_new_elusive_or_friendly_control_is_not_retargeted_by_extra_bodies(self):
        for mode in('elusive','control'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,enemy=(A,B,C,D,E));ids=self.ids(g);self.start(g,ids[4])
                self.assertEqual(self.hp(g,ids),(18,18,18,20,18));self.assertEqual(g.state.players[1].overload_owed,3)
                self.portable(g)

    def test_departed_secondary_is_not_replaced_and_other_original_arrows_still_execute(self):
        g=self.game(mode='return_secondary',enemy=(A,B,C,D,E));ids=self.ids(g);self.start(g,ids[4])
        self.assertIn(ids[4],g.state.players[2].hand);self.assertEqual(self.hp(g,ids[:4]),(18,18,18,20))
        self.assertEqual(g.state.players[1].overload_owed,3);self.portable(g)

    def test_removed_original_neighbor_does_not_rebind_same_name_new_summon(self):
        g=self.game(mode='replace_neighbor');ids=self.ids(g);hero=g.state.players[2].hero_id;self.start(g)
        new=next(i for i in self.ids(g)if i not in ids);self.assertEqual(g.state.entities[new].health,20)
        self.assertIn(ids[0],g.state.players[2].hand);self.assertEqual(self.hp(g,ids[1:]),(18,18))
        self.assertEqual(g.state.entities[hero].health,26);self.assertEqual(g.state.players[1].overload_owed,2)

    def test_each_damage_packet_uses_real_spell_damage(self):
        g=self.game(board=(SD,));ids=self.ids(g);hero=g.state.players[2].hero_id;self.start(g)
        self.assertEqual(self.hp(g,ids),(16,16,16));self.assertEqual(g.state.entities[hero].health,18)
        self.assertEqual(g.state.players[1].overload_owed,3)

    def test_countered_group_keeps_original_program_for_next_accepted_pair(self):
        g=self.game(hand=(CARD,SET,BE,BE));ids=self.ids(g);self.play(g,CARD);self.play(g,SET)
        self.pair(g,ids[1],g.state.players[2].hero_id);self.assertEqual(self.cast(g).failure,'countered')
        self.assertTrue(any(e.spec_id==native.PROGRAM for e in g.state.players[1].player_effects))
        self.pair(g,ids[1],g.state.players[2].hero_id);self.assertEqual(self.hp(g,ids),(18,18,18))
        self.assertEqual(g.state.players[1].overload_owed,3);self.portable(g)

    def test_actual_automatic_explicit_pair_preserves_both_arrow_materials(self):
        mode='auto';g=self.game(mode=mode,hand=(CARD,driver(mode)));ids=self.ids(g);self.play(g,CARD);self.play(g,driver(mode))
        self.assertEqual(self.cast(g).origin,'effect');self.assertEqual(self.hp(g,ids),(18,18,18))
        self.assertEqual(g.state.players[1].overload_owed,3);self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_automatic_random_pair_uses_only_original_two_draws_across_restored_body_wait(self):
        def selected(seed):
            rng=random.Random(seed);first=rng.randrange(4);rest=[i for i in range(4)if i!=first]
            return first==2 and rest[rng.randrange(3)]==0
        seed=next(i for i in range(500)if selected(i));mode='accepted'
        g=self.game(mode=mode,hand=(CARD,driver(mode)),seed=seed);ids=self.ids(g);hero=g.state.players[2].hero_id
        self.play(g,CARD);self.play(g,driver(mode));self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(tuple(f.entity_id for f in self.cast(g).spell_target_receipt.targets),(ids[1],hero))
        rng=g.snapshot()['rng_state'];g=self.portable(g);self.choose(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.players[1].overload_owed,3);self.portable(g)

    def test_every_overload_wait_restores_full_pair_and_original_body_order(self):
        g=self.game(mode='overload');ids=self.ids(g);self.start(g);original=asdict(self.cast(g).spell_target_receipt)
        for cursor in(0,1,3):
            self.assertEqual(self.cast(g).next_spell_body_cursor,cursor);g=self.portable(g);self.choose(g)
        self.assertEqual(asdict(self.cast(g).spell_target_receipt),original)
        self.assertEqual(self.hp(g,ids),(18,18,18));self.assertEqual(g.state.players[1].overload_owed,3)

    def test_failed_extra_body_choice_preserves_payment_pair_progress_and_rng(self):
        g=self.game(mode='overload');self.start(g);self.choose(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);g=self.portable(g);self.drain(g);self.assertEqual(g.state.players[1].overload_owed,3)

    def test_second_player_and_invalid_original_input_keep_original_admission_rules(self):
        g=self.game(active=2);ids=self.ids(g,1);self.start(g,p=2)
        self.assertEqual(self.hp(g,ids),(18,18,18));self.assertEqual(g.state.players[2].overload_owed,3)
        self.portable(g)
        g=self.game();ids=self.ids(g);self.play(g,CARD);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.pair(g,ids[1],g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(),saved)

    def test_rehashed_saved_cast_cannot_replace_original_actual_second_arrow(self):
        g=self.game();self.start(g);bad=deepcopy(g.snapshot());receipt=bad['state']['cast_history'][-1]['spell_target_receipt']
        receipt['targets'][1]=deepcopy(receipt['targets'][0]);receipt['presences'][1]=deepcopy(receipt['presences'][0])
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(rehash(bad),fixture('normal','independent-reader'))
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_private_original_group_and_body_material_are_not_player_dto_fields(self):
        g=self.game();self.start(g)
        for player in(1,2):
            dto=json.dumps(g.for_player(player).observe())
            for field in('spell_target_receipt','spell_target_group','next_spell_body_board','next_spell_body_behaviors','resolution_frame','rng_state'):
                self.assertNotIn('"'+field+'"',dto)

    def test_real_standard_host_uses_two_original_arrows_and_three_full_body_effects(self):
        self.mode='host';h=host('writer');plain='CORE_CS2_120'
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(CARD,BE),mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=(plain,)*3,mana=10,max_mana=10)),generation_context=h.context,seed=680),h.registry)
        ids=self.ids(g);hero=g.state.players[2].hero_id;self.start(g)
        self.assertEqual(self.hp(g,ids),(1,1,1));self.assertEqual(g.state.entities[hero].health,24)
        self.assertEqual(g.state.players[1].overload_owed,3);self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(len(g.state.cast_history),2);self.portable(g)


if __name__=='__main__':unittest.main()
