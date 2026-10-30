"""Real one-cost Potion components under original Conductivity body windows."""
from copy import deepcopy
from functools import lru_cache
import json,random,unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import build_registry,past_conductivity as native
from hs_sim.cards.kazakus_potion_cards import TEMPLATE,PARTS,DEMON
from hs_sim.engine import Game,PlayCard,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.composed_spells import ComposedSpellRecipe,ResolveComposedSpell,STEP,END
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption,Destroy,InvokeBehavior,RandomDamage,RequestChoice)
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format

CARD=native.ROOTS[0];P='k679.'
A,B,C,ELUSIVE,WATCH,KILL,AUTO,FAIL,D,UNKNOWN=(P+x for x in
    ('a','b','c','elusive','watch','kill','auto','fail','demon','unknown'))
CTX=GenerationContext('k679-original-Potion-adjacent-bodies','experimental')
ASTEROID='GDB_430'


def potion(other):
    return ComposedSpellRecipe(TEMPLATE,*(PARTS[i]for i in sorted((3,other)))).card_id


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=build_registry()
    for cid in(A,B,C,ELUSIVE):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=2,health=20,
            keywords=(Keyword.ELUSIVE,)if cid==ELUSIVE else(),metadata=metadata(collectible=False,tribes=())))
    r.register_card(CardDefinition(D,D,CardType.MINION,attack=1,health=4,metadata=metadata(tribes=('demon',))))
    r.register_pool_card(PoolCard.from_definition(r.card(D)))
    if mode=='unknown':
        r.register_pool_card(PoolCard.from_definition(CardDefinition(UNKNOWN,UNKNOWN,CardType.MINION,
            health=4,metadata=metadata(tribes=('demon',)))))
    r.register_pool(PoolDefinition('constructed.minions','k679-'+mode,CTX.target_id,CTX.mode,
        (PoolMember(UNKNOWN if mode=='unknown'else D),),complete=True))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K679 deliberate body rollback')))
    def watch(c):
        selected=(mode=='wait'and c.event.kind=='minion_summoned'and c.state.entities[c.event.target_id].card_id==DEMON or
            mode=='nested'and c.event.kind=='spell_cast_accepted'and c.state.entities[c.event.source_id].card_id==ASTEROID)
        if not selected:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',
            (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
             InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=(TriggerSpec('minion_summoned',WATCH),TriggerSpec('spell_cast_accepted',WATCH)),
        metadata=metadata(collectible=False,tribes=())))
    r.register_behavior(KILL,lambda c:(Destroy(c.state.players[c.player_id].board[-1],c.source_id),))
    r.register_card(CardDefinition(KILL,KILL,CardType.SPELL,on_play=KILL,metadata=metadata(collectible=False)))
    def auto(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id.startswith('potion:'))
        return(CastStoredSpell(CardReference.capture(source),c.player_id,c.source_id,
            targeting='explicit',target_id=c.state.players[3-c.player_id].board[1]),)
    r.register_behavior(AUTO,auto)
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,cost=1,health=3,on_play=AUTO,
        metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


def rehash(value):
    value['events_hash']=canonical_hash(value['events'])
    value['state_hash']=canonical_hash({k:v for k,v in value.items()if k not in('schema_version','events','events_hash','state_hash')})
    return value


class ConductivityComposedTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(mode,role))
    def game(self,other=4,*,mode='normal',board=(),enemy=(A,B,C),active=1,deck=None,hand=None):
        self.mode=mode;hand=(CARD,potion(other))if hand is None else hand;deck=(A,)*12 if deck is None else deck
        if mode in('wait','nested'):board=(WATCH,*board)
        setups=[]
        for p in(1,2):
            setups.append(PlayerSetup('HERO_08',hand=hand if p==active else(),board=board if p==active else enemy,
                deck=deck if p==active else(),mana=10,max_mana=10))
        return Game.from_scenario(Scenario(tuple(setups),active_player=active,seed=679,generation_context=CTX),fixture(mode,'writer'))
    def ids(self,g,p=2):return tuple(g.state.players[p].board)
    def hp(self,g,ids):return tuple(g.state.entities[i].health for i in ids)
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def cast(self,g):return next(c for c in reversed(g.state.cast_history)if c.card_id.startswith('potion:'))
    def steps(self,g,kind=STEP):return [e for e in g.events if e.kind==kind and dict(e.data)['cast_id']==self.cast(g).id]
    def arm_play(self,g,other=4,p=1,target=None):
        self.play(g,CARD,player=p)
        target=self.ids(g,3-p)[1]if target is None else target
        return self.play(g,potion(other),target,player=p)
    def drain(self,g):
        for _ in range(12):
            if g.state.pending_choice is None:return
            self.choose(g)
        self.fail('Potion body choices did not finish')
    def assert_three(self,g):
        self.assertEqual([dict(e.data).get('spell_body_index')for e in self.steps(g)],[None,None,0,0,1,1])
        self.assertEqual([dict(e.data).get('spell_body_index')for e in self.steps(g,END)],[None,0,1])
        self.assertEqual(self.cast(g).next_spell_body_cursor,4)

    def test_real_damage_armor_components_run_three_times_with_one_cost_and_cast(self):
        g=self.game();ids=self.ids(g);self.arm_play(g)
        self.assertEqual(self.hp(g,ids),(17,17,17));self.assertEqual(self.armor(g),12)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.cast_history),2)
        self.assertEqual(self.cast(g).target_id,ids[1]);self.assert_three(g);self.portable(g)

    def test_actual_area_and_friendly_health_components_read_each_new_body_state(self):
        g=self.game(0);ids=self.ids(g);self.arm_play(g,0);self.assertEqual(self.hp(g,ids),(11,11,11));self.assert_three(g)
        g=self.game(5,board=(A,));ids=self.ids(g);own=self.ids(g,1)[0];self.arm_play(g,5)
        self.assertEqual(g.state.entities[own].health,26);self.assertEqual(self.hp(g,ids),(17,17,17));self.assert_three(g)

    def test_actual_fixed_demons_are_new_physical_entries_attributed_to_original_cast(self):
        g=self.game(1);self.arm_play(g,1);summons=[g.state.entities[i]for i in self.ids(g,1)]
        self.assertEqual([e.card_id for e in summons],[DEMON]*3);self.assertEqual(len({e.id for e in summons}),3)
        self.assert_three(g);self.portable(g)

    def test_actual_resurrection_repeats_original_death_domain_without_reusing_a_live_body(self):
        g=self.game(2,board=(A,),hand=(KILL,CARD,potion(2)));dead=self.ids(g,1)[0];self.play(g,KILL)
        self.arm_play(g,2);ids=self.ids(g,1);self.assertEqual(len(ids),3);self.assertNotIn(dead,ids)
        self.assertEqual([g.state.entities[i].card_id for i in ids],[A]*3);self.assert_three(g)

    def test_actual_draw_and_demon_generation_each_keep_three_independent_deliveries(self):
        for other,expected in ((7,A),(8,D)):
            with self.subTest(component=other):
                g=self.game(other);self.arm_play(g,other)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[expected]*3)
                self.assert_three(g)

    def test_actual_random_freeze_component_uses_existing_rng_and_cast_context(self):
        g=self.game(6);before=g.snapshot()['rng_state'];self.arm_play(g,6)
        self.assertTrue(any(g.state.entities[i].frozen for i in self.ids(g)))
        self.assertNotEqual(g.snapshot()['rng_state'],before);self.assert_three(g);self.portable(g)

    def test_invalid_adjacent_target_skips_both_real_components_without_renumbering(self):
        g=self.game(enemy=(ELUSIVE,B,C));ids=self.ids(g);self.arm_play(g)
        self.assertEqual(self.hp(g,ids),(20,17,17));self.assertEqual(self.armor(g),8)
        self.assertEqual([dict(e.data).get('spell_body_index')for e in self.steps(g)],[None,None,1,1])
        self.assertEqual(self.cast(g).next_spell_body_cursor,4);self.portable(g)

    def test_hero_target_and_targetless_recipe_have_only_original_component_pair(self):
        g=self.game();hero=g.state.players[2].hero_id;self.arm_play(g,target=hero)
        self.assertEqual(g.state.entities[hero].health,27);self.assertEqual(self.armor(g),4)
        self.assertEqual(len(self.steps(g)),2);self.assertEqual(self.cast(g).next_spell_body_board,())
        untargeted=ComposedSpellRecipe(TEMPLATE,PARTS[1],PARTS[4]).card_id
        g=self.game(hand=(CARD,untargeted));self.play(g,CARD);self.play(g,untargeted)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.ids(g,1)),1)
        self.assertEqual(len(self.steps(g)),2);self.portable(g)

    def test_second_player_owns_all_component_effects_and_private_body_slots(self):
        g=self.game(active=2);ids=self.ids(g,1);self.arm_play(g,p=2)
        self.assertEqual(self.hp(g,ids),(17,17,17));self.assertEqual(self.armor(g,2),12);self.assertEqual(self.armor(g,1),0)
        self.assertEqual(g.state.players[2].mana,7);self.assert_three(g);self.portable(g)

    def test_each_real_summon_choice_boundary_restores_original_next_component(self):
        g=self.game(1,mode='wait');ids=self.ids(g);self.arm_play(g,1)
        for cursor in(0,1,3):
            self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.cast(g).next_spell_body_cursor,cursor)
            g=self.portable(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.hp(g,ids),(17,17,17));self.assert_three(g);self.portable(g)

    def test_failed_extra_body_choice_restores_component_progress_and_rng(self):
        g=self.game(1,mode='wait');self.arm_play(g,1);self.choose(g);self.assertEqual(self.cast(g).next_spell_body_cursor,1)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);g=self.portable(g);self.drain(g);self.assert_three(g)

    def test_nested_drawn_asteroid_can_wait_without_invalidating_parent_component(self):
        g=self.game(7,mode='nested',deck=(ASTEROID,)+(A,)*12);self.arm_play(g,7)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.cast_history[-1].card_id,ASTEROID)
        g=self.portable(g);self.choose(g);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.cast_history),3);self.assert_three(g);self.portable(g)

    def test_actual_stored_automatic_recipe_uses_free_cast_and_same_component_protocol(self):
        g=self.game(4,hand=(CARD,potion(4),AUTO));ids=self.ids(g);self.play(g,CARD);self.play(g,AUTO)
        self.assertEqual(self.cast(g).origin,'effect');self.assertEqual(self.hp(g,ids),(17,17,17))
        self.assertEqual(self.armor(g),12);self.assertEqual(g.state.players[1].mana,7);self.assert_three(g);self.portable(g)

    def test_unknown_eligible_demon_is_not_filtered_and_entire_original_action_rolls_back(self):
        g=self.game(8,mode='unknown');self.play(g,CARD);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,potion(8),self.ids(g)[1])
        self.assertEqual(g.snapshot(),saved)

    def test_codec_rejects_borrowed_body_slot_and_unknown_cast(self):
        g=self.game(1,mode='wait');self.arm_play(g,1);self.choose(g);record=self.cast(g)
        codec=FrameCodec(default_mechanics(),g.registry,origin_state=g.state)
        good=ResolveComposedSpell(record.id,1,0);self.assertEqual(codec.decode(codec.encode(good)),good)
        for bad in (ResolveComposedSpell(record.id,1,None),ResolveComposedSpell(record.id,1,1),ResolveComposedSpell(record.id-1,1,0)):
            with self.assertRaises(ValueError):codec.encode(bad)

    def test_rehashed_pending_body_key_cursor_and_missing_field_are_rejected(self):
        g=self.game(1,mode='wait');self.arm_play(g,1);self.choose(g);saved=g.snapshot()
        def edit(value,mode):
            if isinstance(value,dict):
                if value.get('type')=='hs_sim.engine.composed_spells.ResolveComposedSpell':
                    if mode=='body':value['fields']['body_index']=1
                    elif mode=='primary':value['fields']['body_index']=None
                    elif mode=='cursor':value['fields']['index']=2
                    else:value['fields'].pop('body_index')
                    return True
                return any(edit(x,mode)for x in value.values())
            if isinstance(value,list):return any(edit(x,mode)for x in value)
            return False
        for mode in('body','primary','cursor','missing'):
            bad=deepcopy(saved);self.assertTrue(edit(bad,mode))
            with self.subTest(mode=mode),self.assertRaises(SnapshotError) as caught:
                Game.from_snapshot(rehash(bad),fixture('wait','independent-reader'))
            self.assertNotIn('digest mismatch',str(caught.exception))

    def test_rehashed_component_groups_cannot_swap_original_body_windows(self):
        g=self.game();self.arm_play(g);saved=g.snapshot();changed=False
        for event in saved['events']:
            if event['kind']not in(STEP,END):continue
            data=dict(event['data'])
            if data.get('spell_body_index')is None:continue
            data['spell_body_index']=1-data['spell_body_index'];event['data']=[list(x)for x in data.items()];changed=True
        self.assertTrue(changed)
        with self.assertRaises(SnapshotError) as caught:Game.from_snapshot(rehash(saved),fixture('normal','independent-reader'))
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_body_keys_and_full_proofs_are_not_player_dto_fields(self):
        g=self.game();self.arm_play(g)
        for p in(1,2):
            dto=json.dumps(g.for_player(p).observe())
            for field in('spell_body_index','body_index','adjacent_board_json','next_spell_body_behaviors','resolution_frame','rng_state'):
                self.assertNotIn('"'+field+'"',dto)

    def test_real_standard_host_coin_generates_recipe_then_complete_adjacent_bodies(self):
        self.mode='host';h=host('writer');coin='JAIL_504t3';plain='CORE_CS2_120'
        seed=next(i for i in range(500)if sorted(random.Random(i).sample(range(9),2))==[3,4])
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hand=(coin,CARD),mana=8,max_mana=10),
            PlayerSetup('HERO_08',board=(plain,)*3,mana=10,max_mana=10)),seed=seed,generation_context=h.context),h.registry)
        self.play(g,coin);self.assertEqual(self.entity(g,potion(4)).card_id,potion(4));ids=self.ids(g)
        self.arm_play(g);self.assertEqual(self.armor(g),12);self.assertEqual(g.state.players[1].mana,6)
        self.assertEqual(len(g.state.cast_history),3);self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in ids))
        self.assert_three(g);self.portable(g)


if __name__=='__main__':unittest.main()
