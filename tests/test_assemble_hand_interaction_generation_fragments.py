"""Actual hand/deck movements and generated cards keep native delivery rules."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_hand_interaction_generation_fragments import (
    SOURCES,LYNX,ROCK,load_batch,register_assemble_hand_interaction_generation_fragments)
from hs_sim.cards.native_assemble_entry_cards import FLESH,POOL_ID as ASSEMBLY_POOL
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,GainArmor,InvokeBehavior,
    RequestChoice,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,Keyword,Rarity,RewindSpec,SpellSchool,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture,META,COIN,KILL,MUTE

RAT,GUARD,GNOME,HALAZZI,LORD,DRAGON,MACHINE,MEMORY,CHAMPION,ROCKER,TERROR,MENDER=SOURCES
FLY,LOOT,END,START='CORE_UNG_809','CORE_EX1_096','EDR_971','CORE_NEW1_021'
P='fixture.assemble_hand_interaction.'
D2,L2,R2,N2,HOLY,SHADOW,PAST5,STANDARD5=(P+x for x in
    ('dragon','legend','rewind','ordinary','holy','shadow','past_five','standard_five'))
PAST_COLOSSAL='TSC_216'
GENERAL=(D2,L2,R2,N2,HOLY,SHADOW,STANDARD5)
GENERATED=GENERAL+(PAST5,PAST_COLOSSAL,LYNX,ROCK)
WATCH,FAULT,GIVE,SUMMON,UNKNOWN=(P+x for x in ('watch','fault','give','summon','unknown'))
POOL,PAST_POOL='constructed.cards','constructed.past.cards'
CTX=GenerationContext('k412-reviewed-hand-interaction-domain','experimental')


def face(prefix,suffix):return AssembleRecipe(prefix,suffix,'bottom').card_id


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k412.'+mode
    r.register_behavior(P+'noop',lambda c:())
    def metadata(tribes=(),legend=False):
        return CardMetadata(True,(CardClass.NEUTRAL,),Rarity.LEGENDARY if legend else Rarity.COMMON,tribes=tribes)
    for cid,cost,tribes,legend in ((D2,2,('dragon',),False),(L2,2,(),True),
            (R2,2,(),False),(N2,2,(),False),(PAST5,5,(),False),(STANDARD5,5,(),False)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,
            keywords=(Keyword.REWIND,)if cid==R2 else(),rewind=RewindSpec()if cid==R2 else None,
            battlecry=P+'noop'if cid==R2 else None,
            metadata=metadata(tribes,legend))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    for cid,school in ((HOLY,SpellSchool.HOLY),(SHADOW,SpellSchool.SHADOW)):
        d=CardDefinition(cid,cid,CardType.SPELL,cost=3,on_play=P+'noop',spell_school=school,metadata=metadata())
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    members=GENERAL
    if mode in('two_only','flesh'):members=(N2,)
    if mode=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,2,metadata(('dragon',),True),keywords=(Keyword.REWIND,)))
        members=(UNKNOWN,)
    if mode=='unknown_shadow':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,3,metadata(),spell_school=SpellSchool.SHADOW))
        members=(HOLY,UNKNOWN)
    if mode not in ('no_general','no_domains'):
        r.register_pool(PoolDefinition(POOL,'complete-diagnostic-current-domain-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid)for cid in members),complete=True))
    if mode not in ('no_past','no_domains'):
        r.register_pool(PoolDefinition(PAST_POOL,'complete-diagnostic-past-domain-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid)for cid in(PAST5,PAST_COLOSSAL)),complete=True))
    if mode=='missing':r._assemble_templates.pop(TERROR)
    if mode!='no_assembly':
        r.register_pool(PoolDefinition(ASSEMBLY_POOL,'three-real-hand-interaction-sources-v1',CTX.target_id,CTX.mode,
            tuple(PoolMember(cid)for cid in((LOOT,TERROR,'CORE_SW_072')if mode=='flesh'else(LOOT,TERROR,FLY))),complete=True))
    def fault(c):raise ResolutionError('assembled hand interaction deliberate failure')
    def watch(c):
        if c.event.player_id!=c.player_id or c.state.entities[c.event.target_id].card_id not in(HOLY,SHADOW):return()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('fault','Fail',(
            GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(FAULT,fault);r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        triggers=(TriggerSpec('card_created',WATCH),)))
    r.register_behavior(GIVE,lambda c:(ChangeControl(c.target_id,2),))
    r.register_card(CardDefinition(GIVE,GIVE,CardType.SPELL,on_play=GIVE,metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    r.register_behavior(SUMMON,lambda c:(Summon(c.player_id,face(FLY,HALAZZI)),))
    r.register_card(CardDefinition(SUMMON,SUMMON,CardType.SPELL,on_play=SUMMON,metadata=META))
    return r


class AssembleHandInteractionTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,mode='normal',hero='HERO_08',seed=412):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=(COIN,)*12 if deck is None else deck,
                mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(N2,COIN,COIN)if enemy_deck is None else enemy_deck,
                mana=30,max_mana=30,mana_cap=30)),seed=seed,generation_context=CTX),fixture(mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid
    def added(self,g,before=(),pid=1):
        return[g.state.entities[i]for i in g.state.players[pid].hand if i not in before]
    def generated(self,g):return[e for e in g.state.entities.values()if e.card_id in GENERATED]
    def price(self,g,e):return quote_cost(g.state,g.registry,e).amount
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_fourteen_complete_records_twenty_eight_full_primary_faces_and_fixed_children(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES+(LYNX,ROCK));self.assertEqual(len(data['official_observations']),28)
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'])
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([f for f in json.loads(path.read_text('utf-8-sig'))['cards']if f['id']==row['record']['dbf_id']],[obs['face']])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        self.assertEqual((r.card(LYNX).cost,r.card(LYNX).attack,r.card(LYNX).health,r.card(LYNX).keywords),(1,1,1,(Keyword.RUSH,)))
        self.assertEqual((r.card(ROCK).cost,r.card(ROCK).kind),(1,CardType.SPELL))

    def test_whole_faces_original_bodies_and_four_reviewed_timings_are_readonly(self):
        r=build_registry();fingerprint=r.fingerprint();count=len(r.cards)
        for cid in SOURCES:
            d=r.card(cid);t=r.assemble_templates[cid]
            self.assertEqual(asdict(r.card(AssembleRecipe(cid,cid,'top').card_id)),asdict(d)|{'id':AssembleRecipe(cid,cid,'top').card_id})
            self.assertEqual(t.suffix.behavior_id,d.battlecry or d.deathrattle)
            self.assertEqual(set(t.suffix.allowed_timings),{'battlecry','deathrattle','start_turn','end_turn'})
            for prefix in(FLY,LOOT,END,START):
                borrowed=r.card(face(prefix,cid));self.assertEqual(borrowed.keywords,r.card(prefix).keywords)
                self.assertEqual((borrowed.cost,borrowed.attack,borrowed.health),
                    (r.card(prefix).cost,r.card(prefix).attack,r.card(prefix).health))
        self.assertEqual((r.fingerprint(),len(r.cards)),(fingerprint,count))

    def test_each_suffix_runs_from_actual_paid_battlecry_with_its_native_request(self):
        for donor in SOURCES:
            with self.subTest(donor=donor):
                cid=face(FLY,donor);g=self.game(hand=(cid,)+(COIN,)*3,enemy_hand=(ROCKER,COIN))
                old_hand=tuple(g.state.players[1].hand);old_enemy=tuple(g.state.players[2].hand);old_deck=tuple(g.state.players[2].deck)
                mana=g.state.players[1].mana;eid=self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,mana-g.registry.card(cid).cost)
                self.assertTrue(g.state.battlecry_history[-1].completed)
                self.assertEqual(g.state.battlecry_history[-1].source_id,eid)
                cards=self.added(g,old_hand);ids=[e.card_id for e in cards]
                if donor==RAT:
                    pulled=old_enemy[0];self.assertIn(pulled,g.state.players[2].board)
                    self.assertEqual(g.state.players[2].hand,[old_enemy[1]])
                    self.assertFalse(any(g.state.entities[i].card_id==ROCK for i in g.state.players[2].hand))
                elif donor==GUARD:
                    self.assertEqual(len(g.state.players[1].hand),1)
                    self.assertEqual(sum(g.state.entities[i].card_id==COIN for i in g.state.players[1].graveyard),2)
                elif donor==GNOME:self.assertEqual(g.state.players[2].deck,list(old_deck[1:]))
                elif donor==HALAZZI:
                    self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(ids,[LYNX]*7)
                elif donor==LORD:self.assertEqual(ids,[PAST_COLOSSAL])
                elif donor==DRAGON:
                    self.assertEqual(ids,[D2]);self.assertEqual(self.price(g,cards[0]),0)
                elif donor==MACHINE:self.assertEqual(ids,[R2])
                elif donor==MEMORY:self.assertEqual(ids,[PAST5])
                elif donor==CHAMPION:
                    self.assertEqual(ids,[L2]);self.assertEqual(self.price(g,cards[0]),1)
                elif donor==ROCKER:self.assertEqual(ids,[ROCK])
                elif donor==TERROR:
                    self.assertEqual(len(cards),2);self.assertEqual(len({e.id for e in cards}),2)
                    self.assertTrue(all(g.registry.card(e.card_id).cost==2 and e.hand_lifetime.expires_turn==g.state.turn for e in cards))
                elif donor==MENDER:self.assertEqual(ids,[HOLY,SHADOW])

    def test_real_flesh_entry_creates_natural_death_body_without_old_loot_draw(self):
        cid=face(LOOT,TERROR);g=self.game(hand=(FLESH,KILL),mode='flesh',hero='HERO_07',seed=1);self.play(g,FLESH)
        self.choose(g,next(x.id for x in g.state.pending_choice.options if x.card_id==cid))
        eid=self.play(g,cid);self.assertFalse(any(e.card_id==N2 for e in self.added(g)))
        before=tuple(g.state.players[1].hand);self.play(g,KILL,eid);cards=self.added(g,before)
        self.assertEqual([e.card_id for e in cards],[N2,N2]);self.assertTrue(all(e.hand_lifetime.expires_turn==g.state.turn for e in cards))
        self.assertFalse(g.state.draw_history);self.assertTrue(g.state.deathrattle_history[-1].completed)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)

    def test_natural_death_top_removal_and_silenced_generation_keep_physical_zones(self):
        cid=face(LOOT,GNOME);g=self.game(hand=(KILL,),board=(cid,),enemy_deck=(HOLY,SHADOW))
        original=list(g.state.players[2].deck);eid=g.state.players[1].board[0];self.play(g,KILL,eid)
        self.assertEqual(g.state.players[2].deck,[original[1]])
        self.assertNotIn(original[0],g.state.players[2].graveyard);self.assertFalse(g.state.draw_history)
        silent=face(LOOT,TERROR);g=self.game(hand=(MUTE,KILL),board=(silent,),mode='no_domains')
        eid=g.state.players[1].board[0];self.play(g,MUTE,eid);self.play(g,KILL,eid)
        self.assertFalse(any(e.kind=='card_created'for e in g.events))

    def test_transferred_owner_start_summons_current_opponent_physical_card_without_battlecry(self):
        cid=face(START,RAT);g=self.game(hand=(cid,GIVE,ROCKER,COIN))
        eid=self.play(g,cid);self.play(g,GIVE,eid);rat=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==ROCKER)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[eid].controller,2)
        self.assertIn(rat,g.state.players[1].board);self.assertNotIn(rat,g.state.players[1].hand)
        self.assertFalse(any(g.state.entities[i].card_id==ROCK for i in g.state.players[1].hand))

    def test_owner_end_removes_one_top_card_without_original_healing(self):
        cid=face(END,GNOME);g=self.game(hand=(cid,),enemy_deck=(HOLY,SHADOW))
        deck=list(g.state.players[2].deck);self.play(g,cid);self.assertEqual(g.state.players[2].deck,deck)
        g.apply(EndTurn(1));self.assertEqual(g.state.players[2].deck,[])
        self.assertIn(deck[1],g.state.players[2].hand)
        self.assertNotIn(deck[0],g.state.players[2].hand);self.assertNotIn(deck[0],g.state.players[2].graveyard)
        self.assertEqual([e.player_id for e in g.state.draw_history],[2])
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[30,30])

    def test_dead_transferred_source_generates_discounted_card_for_death_controller(self):
        cid=face(LOOT,CHAMPION);g=self.game(hand=(cid,GIVE,KILL));eid=self.play(g,cid);self.play(g,GIVE,eid)
        before=tuple(g.state.players[1].hand);self.play(g,KILL,eid)
        cards=self.added(g,pid=2);self.assertEqual([e.card_id for e in cards],[L2]);self.assertEqual(self.price(g,cards[0]),1)
        self.assertFalse(self.added(g,before));self.assertFalse(g.state.draw_history)

    def test_fixed_lynx_fill_and_rock_damage_need_no_random_domain(self):
        fill,rocker=face(FLY,HALAZZI),face(FLY,ROCKER)
        g=self.game(hand=(fill,rocker),mode='no_domains');self.play(g,fill)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(sum(e.card_id==LYNX for e in self.added(g)),9)
        self.play(g,rocker);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(sum(e.card_id==LYNX for e in self.added(g)),9)
        target=g.state.players[2].hero_id;mana=g.state.players[1].mana;self.play(g,ROCK,target)
        self.assertEqual(g.state.players[1].mana,mana-1);self.assertEqual(g.state.entities[target].health,27)

    def test_played_temporary_card_survives_while_other_physical_copy_expires(self):
        cid=face(FLY,TERROR);g=self.game(hand=(cid,),mode='two_only');self.play(g,cid)
        copies=[e.id for e in self.added(g)];self.assertEqual(len(copies),2);self.assertNotEqual(*copies)
        played=self.play(g,N2);unplayed=next(i for i in copies if i!=played);g.apply(EndTurn(1))
        self.assertIn(played,g.state.players[1].board);self.assertNotIn(unplayed,g.state.players[1].hand)
        self.assertEqual(g.state.entities[unplayed].zone,Zone.GRAVEYARD)

    def test_full_hand_samples_twice_with_same_rng_and_burns_without_refund(self):
        cid=face(FLY,TERROR);empty=self.game(hand=(cid,),mode='two_only');self.play(empty,cid)
        full=self.game(hand=(cid,)+(COIN,)*9,mode='two_only');mana=full.state.players[1].mana;self.play(full,cid)
        self.assertEqual([e.card_id for e in self.generated(full)],[e.card_id for e in self.generated(empty)])
        self.assertEqual(full.snapshot()['rng_state'],empty.snapshot()['rng_state'])
        self.assertEqual(len(full.state.players[1].hand),10);self.assertEqual(full.state.players[1].mana,mana-1)
        self.assertTrue(any(e.kind=='card_burned'for e in full.events))

    def test_first_holy_arrival_wait_restores_replays_and_failed_resume_does_not_duplicate(self):
        cid=face(FLY,MENDER);g=self.game(hand=(cid,),board=(WATCH,));eid=self.play(g,cid)
        self.assertEqual(g.state.pending_choice.player_id,1);saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'hand interaction deliberate failure'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        self.choose(g,'ok');self.assertEqual([e.card_id for e in self.added(g)],[HOLY,SHADOW])
        self.assertEqual(len(g.state.battlecry_history),1);self.assertTrue(g.state.battlecry_history[0].completed)
        self.assertEqual(g.state.battlecry_history[0].source_id,eid);self.portable(g)
        opponent=json.dumps(g.observe(2),ensure_ascii=False)
        for private in('rng_before','candidate_card_ids','resolution_frame','generation_policy'):self.assertNotIn(private,opponent)

    def test_missing_domains_and_unknown_eligible_members_rollback_payment_rng_and_first_school(self):
        cases=[('no_past',LORD),('no_past',MEMORY),('no_general',DRAGON),
            *[('unknown',donor)for donor in(DRAGON,MACHINE,CHAMPION,TERROR)],('unknown_shadow',MENDER)]
        for mode,donor in cases:
            with self.subTest(mode=mode,donor=donor):
                cid=face(FLY,donor);g=self.game(hand=(cid,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)

    def test_changed_complete_source_or_child_never_partially_installs_twelve_templates(self):
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        original=dict(r.assemble_templates)
        for cid in SOURCES+(LYNX,ROCK):
            with self.subTest(source=cid):
                old=r._cards[cid];r._cards[cid]=replace(old,name=old.name+' changed')
                try:
                    with self.assertRaises(TargetValidationError):register_assemble_hand_interaction_generation_fragments(r)
                    self.assertEqual(dict(r.assemble_templates),original)
                finally:r._cards[cid]=old
        register_assemble_hand_interaction_generation_fragments(r)
        self.assertTrue(set(SOURCES)<=set(r.assemble_templates))

    def test_missing_assembly_domain_or_source_rolls_back_real_entry_without_pruning(self):
        for mode in('missing','no_assembly'):
            with self.subTest(mode=mode):
                g=self.game(hand=(FLESH,),mode=mode);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,FLESH)
                self.assertEqual(g.snapshot(),saved)

    def test_natural_summon_does_not_execute_borrowed_battlecry(self):
        g=self.game(hand=(SUMMON,),mode='no_domains');self.play(g,SUMMON)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[face(FLY,HALAZZI)])
        self.assertFalse(g.state.players[1].hand);self.assertFalse(g.state.battlecry_history)
