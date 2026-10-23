"""Complete fixed token generation, native keyword material and shared lifecycles."""
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_fixed_keyword_token_cards import (
    DRONE,STONE,SPARKS,ADVENTURERS,DEPENDENCIES,SPARK_BONUSES,ADVENTURER_BONUSES,
    KEYWORDS,load_batch,register_past_fixed_keyword_token_cards)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,Keyword,PlayCard,PlayerSetup,Rarity,Scenario,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,
    InvokeBehavior,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import DamageKind,EndTurnSpec
from hs_sim.engine.pools import PoolMember,sample_candidates
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.registry import UnsupportedDefinitionError

P='k479.';HOST=P+'host';FILLER=P+'filler';WATCH=P+'watch';KILLER=P+'killer'
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=defaults();register_past_fixed_keyword_token_cards(r);r._version='k479-'+mode
    r.register_card(CardDefinition(HOST,HOST,CardType.MINION,cost=2,attack=2,health=4,
        metadata=replace(META,tribes=('mech',))))
    r.register_card(CardDefinition(FILLER,FILLER,CardType.MINION,cost=3,attack=1,health=30,metadata=META))
    def fail(c):raise ResolutionError('K479 deliberate late acquisition failure')
    def end_kill(c):
        return tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==STONE)
    scripts={
        'hurt':lambda c:(Damage(c.state.players[c.player_id].hero_id,12,c.source_id),),
        'ping':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'kill_host':lambda c:tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==HOST),
        'silence':lambda c:(Silence(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'summon':lambda c:(Summon(c.player_id,DRONE),),'fail':fail,'end_kill':end_kill,
    }
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        if key not in('fail','end_kill'):r.register_card(CardDefinition(P+key,key,CardType.SPELL,
            on_play=P+key,requires_target=key in('ping','kill','silence','give'),metadata=META))
    def watch(c):
        e=c.event
        if e.kind=='minion_summoned'and c.state.entities[e.target_id].card_id==DRONE:
            if mode=='fill':return (AddToHand(c.player_id,FILLER,c.source_id),)
            if mode=='before':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),c.source_id),)
        if e.kind=='card_added_to_hand'and e.source_id is not None and c.state.entities[e.source_id].card_id in(DRONE,STONE):
            if mode=='late_fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='after':return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,
        metadata=META,triggers=(TriggerSpec('minion_summoned',WATCH),TriggerSpec('card_added_to_hand',WATCH))))
    r.register_card(CardDefinition(KILLER,KILLER,CardType.MINION,health=9,metadata=META,
        triggers=(TriggerSpec('turn_ended',P+'end_kill',EndTurnSpec()),)))
    if mode=='missing':r._cards.pop(SPARKS[-1])
    r.validate();return r


class PastFixedKeywordTokenTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(FILLER,),mode='normal',seed=479):
        self.mode=mode
        if mode in('fill','before','after','late_fail'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(FILLER,)*4,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',board=enemy,deck=(FILLER,)*4,mana=40,max_mana=40,mana_cap=40,
                hero_power_card_id='HERO_08bp')),seed=seed),fixture(mode))

    def issued(self,g,source=None):
        return [g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'
            and g.state.entities[e.target_id].card_id in(*SPARKS,*ADVENTURERS)
            and(source is None or e.source_id==source)]

    def play_at(self,g,cid,position):
        source=self.entity(g,cid).id;g.apply(PlayCard(1,source,position=position));return source

    def test_complete_26_rows_four_parent_faces_and_exact_child_relations(self):
        data=load_batch();self.assertEqual((len(data['dependencies']),len(data['evidence_only']),len(data['official_observations'])),(18,8,4))
        raw={r['record']['id']:r['record']for r in data['dependencies']}
        for face in data['official_observations']:
            self.assertEqual(batch.sha(face['response_file']),face['response_sha256'])
            batch.check_face(raw[face['card_id']],face['face'],face['locale'],
                numeric_normalizations=data['numeric_normalizations'].get(face['card_id']))
            self.assertEqual(face['face']['childIds'],[raw[c]['dbf_id']for c in data['child_pools'][face['card_id']]])
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_all_sixteen_tokens_keep_full_printed_keywords_stats_and_metadata(self):
        r=fixture();raw={x['record']['id']:x['record']for x in load_batch()['dependencies']}
        for cid,bonus in (*zip(SPARKS,SPARK_BONUSES),*zip(ADVENTURERS,ADVENTURER_BONUSES)):
            with self.subTest(cid=cid):
                c=r.card(cid);spark=cid in SPARKS
                self.assertEqual((c.cost,c.attack,c.health),(1,1,1)if spark else(2,2,2))
                expected=((Keyword.MAGNETIC,)if spark else())+(()if bonus=='SPELLPOWER'else(KEYWORDS[bonus],))
                self.assertEqual(c.keywords,expected);self.assertEqual(c.spell_damage,1 if bonus=='SPELLPOWER'else 0)
                self.assertEqual(c.metadata.rarity,Rarity.NONE);self.assertFalse(c.metadata.collectible)
                self.assertEqual(raw[cid]['tags'].get(bonus),1)
        self.assertEqual(r.card('WC_034t6').metadata.tribes,('undead',))
        self.assertEqual((r.card(STONE).attack,r.card(DRONE).metadata.tribes),(0,('mech',)))
        self.assertTrue(all(r.card(cid).magnetic_tribes==('mech',)for cid in SPARKS))

    def test_actual_drone_sampling_covers_each_native_material_without_replay_per_token(self):
        seeds={}
        for seed in range(256):
            selected,=sample_candidates(random.Random(seed),tuple(PoolMember(i)for i in sorted(SPARKS)),1,replacement=True)
            seeds.setdefault(selected,seed)
            if len(seeds)==8:break
        self.assertEqual(set(seeds),set(SPARKS))
        for expected,seed in seeds.items():
            with self.subTest(cid=expected):
                g=self.game((DRONE,),seed=seed);source=self.play(g,DRONE);token,=self.issued(g,source)
                self.assertEqual(token.card_id,expected);self.assertEqual((token.cost,token.attack,token.health),(1,1,1))
                self.assertIn(Keyword.MAGNETIC,token.keywords);self.assertIn(token.id,g.state.players[1].hand)
                self.assertEqual(g.state.players[1].mana,39);self.assertFalse(g.state.card_discovery_history)

    def test_generated_spark_can_fuse_into_its_real_drone_without_another_battlecry(self):
        g=self.game((DRONE,));source=self.play(g,DRONE);token,=self.issued(g,source)
        self.play_at(g,token.card_id,0)
        self.assertEqual(g.state.players[1].board,[source])
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,3))
        self.assertEqual((g.state.entities[token.id].zone,len(self.issued(g)),g.state.players[1].mana),(Zone.GRAVEYARD,1,38))
        self.assertEqual(len(g.state.magnetic_history),1);self.portable(g)

    def test_all_eight_real_magnetic_bonuses_share_normal_attachment_and_combat_lifecycle(self):
        g=self.game((*SPARKS,P+'hurt',P+'kill_host'),board=(HOST,));host=g.state.players[1].board[0]
        self.play(g,P+'hurt')
        for cid in SPARKS:self.play_at(g,cid,0)
        e=g.state.entities[host];self.assertEqual((e.attack,e.health),(10,12))
        self.assertTrue({KEYWORDS[k]for k in SPARK_BONUSES}<=e.keywords);self.assertNotIn(Keyword.MAGNETIC,e.keywords)
        self.assertEqual(len(g.state.magnetic_history),8)
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,host))
        enemy=g.state.players[2].board[0];g.apply(Attack(1,host,enemy))
        self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[host].health,12)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
        g.apply(Attack(1,host,g.state.players[2].hero_id))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,host,g.state.players[2].hero_id))
        self.play(g,P+'kill_host');fresh,=[g.state.entities[i]for i in g.state.players[1].board]
        self.assertNotEqual(fresh.id,host);self.assertEqual((fresh.card_id,fresh.attack,fresh.health),(HOST,2,1))
        self.portable(g)

    def test_each_adventurer_material_can_be_drawn_from_exact_complete_fixed_pool(self):
        observed=set()
        for seed in range(32):
            g=self.game(board=(STONE,),seed=seed);source=g.state.players[1].board[0];g.apply(EndTurn(1))
            token,=self.issued(g,source);self.assertEqual((token.cost,token.attack,token.health),(2,2,2))
            observed.add(token.card_id)
            if observed==set(ADVENTURERS):break
        self.assertEqual(observed,set(ADVENTURERS))

    def test_arcane_adventurer_printed_spell_power_reaches_ordinary_spell_damage(self):
        g=self.game((ADVENTURERS[4],P+'ping'));self.play(g,ADVENTURERS[4]);target=g.state.players[2].board[0]
        self.play(g,P+'ping',target);self.assertEqual(g.state.entities[target].health,28)

    def test_stone_own_turn_scope_and_control_transfer_use_current_controller(self):
        g=self.game((P+'give',),board=(STONE,));stone=g.state.players[1].board[0]
        self.play(g,P+'give',stone);g.apply(EndTurn(1));self.assertFalse(self.issued(g))
        g.apply(EndTurn(2));token,=self.issued(g,stone);self.assertEqual((token.owner,token.controller),(2,2));self.portable(g)

    def test_stone_extra_end_subjects_sample_independently_and_create_new_entities(self):
        g=self.game(board=(STONE,'ICC_901'));source=g.state.players[1].board[0];g.apply(EndTurn(1))
        tokens=self.issued(g,source);self.assertEqual(len(tokens),2);self.assertEqual(len({t.id for t in tokens}),2)
        self.assertTrue(all(t.card_id in ADVENTURERS for t in tokens));self.portable(g)

    def test_accepted_stone_end_subject_survives_earlier_end_body_removal(self):
        g=self.game(board=(KILLER,STONE));stone=g.state.players[1].board[1];g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[stone].zone,Zone.GRAVEYARD);self.assertEqual(len(self.issued(g,stone)),1)

    def test_silenced_or_dead_stone_does_not_get_new_end_subject(self):
        for spell in ('silence','kill'):
            with self.subTest(spell=spell):
                g=self.game((P+spell,),board=(STONE,));self.play(g,P+spell,g.state.players[1].board[0])
                g.apply(EndTurn(1));self.assertFalse(self.issued(g))

    def test_drone_full_hand_burns_complete_chosen_token_and_keeps_sampling(self):
        g=self.game((DRONE,)+(FILLER,)*9,mode='fill');before=g.snapshot()['rng_state'];source=self.play(g,DRONE)
        token,=self.issued(g,source);self.assertEqual(token.zone,Zone.GRAVEYARD)
        self.assertIn(Keyword.MAGNETIC,token.keywords);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertNotEqual(before,g.snapshot()['rng_state'])

    def test_stone_full_hand_uses_ordinary_generated_burn(self):
        g=self.game((FILLER,)*10,board=(STONE,));g.apply(EndTurn(1));token,=self.issued(g)
        self.assertEqual(token.zone,Zone.GRAVEYARD);self.assertEqual((token.attack,token.health),(2,2))

    def test_one_missing_candidate_rejects_even_before_random_choice(self):
        g=self.game((DRONE,),mode='missing');before=g.snapshot()
        with self.assertRaises((ResolutionError,UnsupportedDefinitionError)):self.play(g,DRONE)
        self.assertEqual(g.snapshot(),before)

    def test_ordinary_drone_summon_does_not_run_battlecry(self):
        g=self.game((P+'summon',));self.play(g,P+'summon');self.assertFalse(self.issued(g))

    def test_real_battlecry_repetition_creates_two_sparks_for_one_payment(self):
        g=self.game((DRONE,),board=('LOE_077',));source=self.play(g,DRONE)
        self.assertEqual((len(self.issued(g,source)),g.state.players[1].mana),(2,39))

    def test_wait_before_sampling_restores_same_one_acceptance(self):
        g=self.game((DRONE,),mode='before');self.play(g,DRONE);self.assertFalse(self.issued(g));other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.issued(g)),1)

    def test_wait_after_acquisition_restores_without_duplicate_token(self):
        g=self.game((DRONE,),mode='after');self.play(g,DRONE);self.assertEqual(len(self.issued(g)),1)
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.issued(g)),1)

    def test_stone_end_acquisition_wait_keeps_original_turn_continuation(self):
        g=self.game(board=(STONE,),mode='after');g.apply(EndTurn(1));other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual((len(self.issued(g)),g.state.active_player),(1,2))

    def test_late_failed_acquisition_rolls_back_native_play_and_rng(self):
        g=self.game((DRONE,),mode='late_fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,DRONE)
        self.assertEqual(g.snapshot(),before)

    def test_opponent_cannot_read_selected_generated_hand_token_or_rng(self):
        g=self.game((DRONE,));self.play(g,DRONE);token,=self.issued(g)
        public=json.dumps(g.for_player(2).observe())+json.dumps(g.for_player(2).events())
        self.assertNotIn(token.card_id,public);self.assertNotIn('rng_state',public);self.assertNotIn('card_ids',public)

    def test_current_constructed_registry_registers_all_18_and_keeps_enchantments_evidence_only(self):
        r=build_registry();self.assertTrue(set(DEPENDENCIES)<=set(r.cards))
        self.assertTrue(all(x['record']['id']not in r.cards for x in load_batch()['evidence_only']))
