"""Food Chain's post-Battlecry window and Shokk's full typed discoveries."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.food_chain_quest_cards import POOL_ID, REWARD, ROOT, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    DeckPolicy, DeckSpec, EndTurn, Game, Keyword, MatchSetup, PlayCard,
    PlayerSetup, Rarity, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.card_conditions import UnknownCardFactError
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (Buff, ChoiceOption, InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition,
    PoolMember, PoolQuery, matches_metadata)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial

P='food.test.'
CTX=GenerationContext('food-chain-explicit-fixture','experimental')
BEASTS={attack:P+'beast.'+str(attack) for attack in (1,2,3,5,7)}
GROW,WAIT_BC,LATE,WATCH,BAD,SUMMON=(P+x for x in ('grow','wait_bc','late','watch','bad','summon'))
FILLERS=tuple(P+'filler.'+str(i)for i in range(30))
GEN=tuple(P+f'gen.{attack}.{i}' for attack in (8,6,4)for i in range(3))
BAD9,DRAGON,TOKEN,UNKNOWN=(P+x for x in ('bad9','dragon','token','unknown'))
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('beast',))


@lru_cache(maxsize=None)
def registry(role,mode='normal'):
    assert role in ('writer','reader')
    r=build_registry();plain=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    r.register_behavior(P+'noop',lambda c: ())
    def fail(c):raise ValueError('Food deliberate rollback')
    r.register_behavior(P+'fail',fail)
    for attack,cid in BEASTS.items():r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=3,metadata=META))
    r.register_behavior(P+'grow',lambda c:(Buff(c.source_id,attack=2,source_id=c.source_id),))
    r.register_behavior(P+'wait_bc',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('grow','Grow',(Buff(c.source_id,attack=2,source_id=c.source_id),)),
        ChoiceOption('keep','Keep',())),c.source_id),))
    for cid,body in ((GROW,P+'grow'),(WAIT_BC,P+'wait_bc')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=3,battlecry=body,metadata=META))
    r.register_card(CardDefinition(P+'nonbeast',P+'nonbeast',CardType.MINION,attack=1,health=3,metadata=plain))
    r.register_card(CardDefinition(P+'all',P+'all',CardType.MINION,attack=1,health=3,
        metadata=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('all',))))
    def late(c):
        if c.event.player_id==c.player_id and c.state.entities[c.event.source_id].card_id==BEASTS[3]:
            return (Buff(c.event.source_id,attack=1,source_id=c.source_id),)
        return ()
    r.register_behavior(P+'late',late)
    r.register_card(CardDefinition(LATE,LATE,CardType.MINION,health=9,metadata=plain,
        triggers=(TriggerSpec('card_played',P+'late'),)))
    for cid in FILLERS:r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=P+'noop',metadata=plain))
    r.register_behavior(SUMMON,lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(BEASTS[7]),),SummonCause.capture(c)),))
    r.register_card(CardDefinition(SUMMON,SUMMON,CardType.SPELL,on_play=SUMMON,metadata=plain))
    classes=(CardClass.HUNTER,CardClass.PRIEST,CardClass.NEUTRAL,
        CardClass.WARLOCK,CardClass.DRUID,CardClass.NEUTRAL,
        CardClass.WARRIOR,CardClass.ROGUE,CardClass.NEUTRAL)
    for n,(cid,cls)in enumerate(zip(GEN,classes)):
        attack=int(cid.split('.')[-2]);card=CardDefinition(cid,cid,CardType.MINION,cost=5+n,attack=attack,health=3,
            metadata=CardMetadata(True,(cls,),Rarity.COMMON,tribes=('beast',)))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    for cid,attack,tribes,collectible in ((BAD9,9,('beast',),True),(DRAGON,8,('dragon',),True),(TOKEN,6,('beast',),False)):
        card=CardDefinition(cid,cid,CardType.MINION,cost=5,attack=attack,health=3,
            metadata=CardMetadata(collectible,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=tribes))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    members=GEN+(BAD9,DRAGON,TOKEN)
    if mode=='short':members=(GEN[1],GEN[7],BAD9,DRAGON,TOKEN)
    elif mode=='empty':members=(BAD9,DRAGON,TOKEN)
    elif mode in ('unknown','unknown_attack'):
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,5,META,battlecry=False,deathrattle=False,choose_one=False,
            attack=8 if mode=='unknown' else None));members=members+(UNKNOWN,)
    if mode!='no_pool':r.register_pool(PoolDefinition(POOL_ID,P+'complete-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    def watch(c):
        if c.event.player_id!=c.player_id or c.event.target_id is None or c.state.entities[c.event.target_id].card_id not in GEN:return ()
        if c.source.card_id==BAD:return (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),
            ChoiceOption('fail','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(P+'watch',watch)
    for cid in (WATCH,BAD):r.register_card(CardDefinition(cid,cid,CardType.MINION,health=9,metadata=plain,
        triggers=(TriggerSpec('card_added_to_hand',P+'watch'),)))
    r.validate();r.freeze();return r


class FoodChainTests(unittest.TestCase):
    def game(self,hand=(ROOT,),*,board=(),enemy_hand=(),mode='normal'):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=hand,board=board,mana=10,max_mana=10,deck=FILLERS),
            PlayerSetup('HERO_08',hand=enemy_hand,mana=10,max_mana=10,deck=FILLERS)),seed=248830,generation_context=CTX),registry('writer',mode))
    def play(self,g,cid):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid));return eid
    def choose(self,g,key=None):
        q=g.state.pending_choice;key=q.options[0].id if key is None else key
        return g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def quest(self,g):return g.state.entities[g.state.players[1].quests[0]].quest_progress
    def names(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].hand)
    def portable(self,g,mode='normal'):
        role='reader' if g.registry is registry('writer',mode)else 'writer'
        r=registry(role,mode);s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,r)
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s);return other
    def matches(self,attack,wanted,*,kind=CardType.MINION,meta=META):
        return matches_metadata(PoolQuery(attack_equals=wanted),card_id='candidate',kind=kind,cost=1,
            meta=meta,spell_school=None,keywords=(),printed_attack=attack)

    def test_a00_full_source_two_faces_each_real_quest_and_rush_reward_body(self):
        from tools.card_batch import check_face
        d=load_batch();rows={x['record']['id']:x['record']for k in ('cards','dependencies')for x in d[k]}
        self.assertEqual(len(d['official_observations']),4)
        for x in d['official_observations']:check_face(rows[x['card_id']],x['face'],x['locale'])
        self.assertEqual((rows[REWARD]['cost'],rows[REWARD]['attack'],rows[REWARD]['health']),(5,9,9))

    def test_a01_exact_printed_attack_is_strict_nullable_conjunctive_and_roundtrips(self):
        from hs_sim.engine.pool_summons import query_from_dict
        for value in (True,-1,1.0,'8'):
            with self.subTest(value=value),self.assertRaises(ValueError):PoolQuery(attack_equals=value)
        self.assertTrue(self.matches(0,0));self.assertTrue(self.matches(8,8));self.assertFalse(self.matches(9,8))
        self.assertFalse(self.matches(None,8,kind=CardType.SPELL))
        with self.assertRaises(UnknownCardFactError):self.matches(None,8)
        for value in (True,-1,8.0):
            with self.subTest(printed_attack=value),self.assertRaises(ValueError):self.matches(value,8)
        q=PoolQuery(kinds=(CardType.MINION,),attack_equals=8,attack_parity='even')
        self.assertEqual(query_from_dict(json.loads(json.dumps(asdict(q)))),q)
        excluded=PoolQuery(min_cost=3,attack_equals=8)
        self.assertFalse(matches_metadata(excluded,card_id='two-cost',kind=CardType.MINION,
            cost=2,meta=META,spell_school=None,keywords=(),printed_attack=None))
        alternatives=PoolQuery(attack_equals=8,any_of=(PoolQuery(attack_parity='odd'),PoolQuery(min_cost=3)))
        self.assertTrue(matches_metadata(alternatives,card_id='eight',kind=CardType.MINION,
            cost=3,meta=META,spell_school=None,keywords=(),printed_attack=8))

    def test_a02_current_catalog_patch_stats_drive_the_pool_without_named_exclusions(self):
        r=registry('writer')
        for cid,wanted in (('EDR_489',False),('CATA_699',True),('DINO_421',True)):
            row=r.pool_cards[cid]
            self.assertEqual(matches_metadata(PoolQuery(kinds=(CardType.MINION,),tribes_any=('beast',),attack_equals=8),
                card_id=cid,kind=row.kind,cost=row.cost,meta=row.metadata,spell_school=row.spell_school,
                keywords=row.keywords,printed_attack=row.attack),wanted)

    def test_a03_actual_thirty_card_opening_guarantees_root_and_recovers_mulligan(self):
        r=registry('writer');decks=(DeckSpec('HERO_05','HERO_05bp',CardClass.HUNTER,(ROOT,*FILLERS[:29])),
            DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,FILLERS))
        policy=DeckPolicy(P+'policy',CTX.target_id,'experimental',tuple(r.cards))
        g=Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=248830,first_player=1),r)
        self.assertIn(ROOT,self.names(g));g=self.portable(g)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.play(g,ROOT);self.assertEqual(self.quest(g).value,0);self.portable(g)

    def test_b00_four_distinct_attacks_in_any_order_give_original_shokk_only_once(self):
        g=self.game((ROOT,BEASTS[7],BEASTS[1],BEASTS[5],BEASTS[3],BEASTS[1]));self.play(g,ROOT)
        for n,attack in enumerate((7,1,5),1):self.play(g,BEASTS[attack]);self.assertEqual(self.quest(g).value,n)
        self.play(g,BEASTS[3]);self.assertFalse(g.state.players[1].quests);self.assertEqual(self.names(g).count(REWARD),1)
        self.play(g,BEASTS[1]);self.assertEqual(self.names(g).count(REWARD),1);self.portable(g)

    def test_b01_duplicate_attacks_and_other_values_do_not_supply_missing_objectives(self):
        g=self.game((ROOT,BEASTS[1],BEASTS[1],BEASTS[2]));self.play(g,ROOT)
        for cid in (BEASTS[1],BEASTS[1],BEASTS[2]):self.play(g,cid)
        self.assertEqual((self.quest(g).value,self.quest(g).keys),(1,('attack:1',)));self.portable(g)

    def test_b02_after_battlecry_attack_is_used_instead_of_the_submitted_printed_one(self):
        g=self.game((ROOT,GROW));self.play(g,ROOT);eid=self.play(g,GROW)
        self.assertEqual(g.state.entities[eid].attack,3)
        self.assertEqual(self.quest(g).keys,('attack:3',));self.portable(g)

    def test_b03_battlecry_wait_does_not_progress_early_and_restores_before_stat_change(self):
        g=self.game((ROOT,WAIT_BC));self.play(g,ROOT);self.play(g,WAIT_BC)
        self.assertEqual(self.quest(g).value,0);g=self.portable(g);self.choose(g,'grow')
        self.assertEqual(self.quest(g).keys,('attack:3',));self.portable(g)

    def test_b04_later_played_reaction_cannot_change_the_already_captured_attack(self):
        g=self.game((ROOT,BEASTS[3]),board=(LATE,));self.play(g,ROOT);eid=self.play(g,BEASTS[3])
        self.assertEqual(g.state.entities[eid].attack,4);self.assertEqual(self.quest(g).keys,('attack:3',));self.portable(g)

    def test_b05_nonbeast_prior_plays_summons_and_enemy_plays_do_not_count(self):
        g=self.game((BEASTS[1],ROOT,P+'nonbeast',SUMMON),enemy_hand=(BEASTS[3],))
        self.play(g,BEASTS[1]);self.play(g,ROOT);self.play(g,P+'nonbeast');self.play(g,SUMMON)
        self.assertEqual(self.quest(g).value,0);g.apply(EndTurn(1));self.play(g,BEASTS[3])
        self.assertEqual(self.quest(g).value,0);self.portable(g)

    def test_b06_all_tribe_minion_is_a_beast_and_progress_remains_player_private(self):
        g=self.game((ROOT,P+'all'));self.play(g,ROOT);self.play(g,P+'all')
        self.assertEqual(self.quest(g).keys,('attack:1',))
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            self.assertNotIn('attack:1',wire);self.assertNotIn('"play_history"',wire)

    def test_c00_shokk_uses_three_printed_attack_groups_any_class_with_cost_set_to_two(self):
        g=self.game((REWARD,));self.play(g,REWARD);picked=[]
        for attack in (8,6,4):
            q=g.state.pending_choice;self.assertIsNotNone(q)
            self.assertTrue(all(g.registry.card(o.card_id).attack==attack for o in q.options))
            if attack==8:self.assertEqual({g.registry.card(o.card_id).metadata.classes[0]for o in q.options},{CardClass.HUNTER,CardClass.PRIEST,CardClass.NEUTRAL})
            cid=q.options[0].card_id;picked.append(cid);self.choose(g)
            eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
            self.assertEqual(quote_cost(g.state,g.registry,g.state.entities[eid]).amount,2)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),3)
        self.assertEqual(self.names(g),tuple(picked));self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_c01_each_original_discovery_wait_restores_independent_registry_and_order(self):
        g=self.game((REWARD,));self.play(g,REWARD)
        for attack in (8,6,4):
            g=self.portable(g);self.assertTrue(all(g.registry.card(o.card_id).attack==attack for o in g.state.pending_choice.options));self.choose(g)
        self.portable(g)

    def test_c02_empty_middle_group_skips_without_replacing_it_with_another_attack(self):
        g=self.game((REWARD,),mode='short');self.play(g,REWARD)
        self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),(GEN[1],));self.choose(g)
        self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),(GEN[7],));self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),2);self.portable(g,'short')

    def test_c03_empty_eligible_pool_does_not_allocate_choices_or_consume_rng(self):
        g=self.game((REWARD,),mode='empty');before=g.snapshot()['rng_state'];self.play(g,REWARD)
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.card_discovery_history)
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g,'empty')

    def test_c04_only_the_first_delivery_fits_full_hand_and_later_discovered_cards_burn(self):
        g=self.game((REWARD,*FILLERS[:9]));self.play(g,REWARD)
        for _ in range(3):self.choose(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.card_discovery_history),3)
        self.assertEqual(sum(e.kind=='card_burned'for e in g._events),2);self.portable(g)

    def test_d00_acquisition_wait_keeps_original_selection_cost_and_two_owed_discoveries(self):
        g=self.game((REWARD,),board=(WATCH,));self.play(g,REWARD);self.choose(g)
        self.assertEqual(tuple(o.id for o in g.state.pending_choice.options),('ok','fail'))
        self.assertEqual(len(g.state.card_discovery_history),1);g=self.portable(g);self.choose(g,'ok')
        self.assertTrue(all(g.registry.card(o.card_id).attack==6 for o in g.state.pending_choice.options));self.portable(g)

    def test_d01_failed_acquisition_choice_rolls_back_to_its_accepted_later_wait(self):
        g=self.game((REWARD,),board=(WATCH,));self.play(g,REWARD);self.choose(g);before=g.snapshot()
        from hs_sim.engine.errors import ResolutionError
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g,'ok');self.portable(g)

    def test_d02_immediate_acquisition_failure_restores_original_offer_rng_and_prior_payment(self):
        g=self.game((REWARD,),board=(BAD,));self.play(g,REWARD);before=g.snapshot()
        from hs_sim.engine.errors import ResolutionError
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,5)

    def test_e00_eligible_unknown_definition_unknown_attack_and_absent_pool_fail_atomically(self):
        from hs_sim.engine.errors import ResolutionError
        for mode in ('unknown','unknown_attack','no_pool'):
            with self.subTest(mode=mode):
                g=self.game((REWARD,),mode=mode);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,REWARD)
                self.assertEqual(g.snapshot(),before)

    def test_f00_current_query_wait_rejects_previous_schema_and_keeps_private_original_work_hidden(self):
        g=self.game((REWARD,));self.play(g,REWARD);s=json.loads(json.dumps(g.snapshot()));s['schema_version']=424
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))
        enemy=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for cid in GEN:self.assertNotIn(cid,enemy)
        for pid in (1,2):
            wire=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in ('"resolution_frame"','"rng_state"','"original_offer"'):self.assertNotIn(key,wire)


if __name__=='__main__':unittest.main()
