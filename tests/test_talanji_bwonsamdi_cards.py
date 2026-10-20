"""Actual Fabled sources exercise persistent named boons and shared deliveries."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.talanji_bwonsamdi_cards import CARD,BWON,SPELL,BOONS,KEYWORDS,PREFIX,POOL_ID,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,EndTurn,
    Game,IllegalAction,Keyword,MatchSetup,PlayCard,PlayerSetup,Rarity,ResolutionError,Runes,Scenario,SelectChoice,
    SnapshotError,SummonQuantitySpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.fabled_decks import expand_fabled_cards
from hs_sim.engine.named_minion_boons import ACCEPTED,material
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,SummonFromPool,validate_pool_entry_keywords
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard

P='fixture.bwonsamdi.';WATCH=P+'watch';DORMANT=P+'dormant';UNKNOWN=P+'unknown';COLOSSAL='CATA_139'
UNITS={cost:P+str(cost)for cost in(4,6,8,10)}
CTX=GenerationContext('bwonsamdi-complete-explicit-experiment','experimental')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal',pool='normal'):
    r=build_registry()
    for cost,cid in UNITS.items():
        c=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=3,health=7,metadata=META)
        r.register_card(c);r.register_pool_card(PoolCard.from_definition(c))
    c=CardDefinition(DORMANT,DORMANT,CardType.MINION,cost=6,attack=3,health=7,dormant_turns=2,metadata=META)
    r.register_card(c);r.register_pool_card(PoolCard.from_definition(c))
    r.register_card(CardDefinition(P+'twice','Quantity provider',CardType.MINION,health=9,
        summon_quantities=(SummonQuantitySpec(),)))
    def fail(c):raise ResolutionError('Boon reaction fixture failure')
    r.register_behavior(P+'fail',fail)
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),'bounce':lambda c:(ReturnToHand(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'get':lambda c:(AddToHand(c.player_id,BWON,c.source_id),),
        'copy':lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode='current',source_id=c.source_id),)}
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if name=='copy'else
                TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name not in('get',)else None))
    def watch(c):
        if mode=='burn'and c.event.kind=='card_committed'and c.state.entities[c.event.source_id].card_id==CARD:
            return(AddToHand(c.player_id,UNITS[4],c.source_id),)
        if mode in('wait','fail')and c.event.kind=='player_effect_added'and dict(c.event.data).get('effect_key','').startswith(PREFIX):
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',
                (InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=tuple(TriggerSpec(k,P+'watch')for k in('card_committed','player_effect_added'))))
    members=tuple(UNITS.values())
    if pool=='dormant':members=(DORMANT,)
    elif pool=='colossal':members=(COLOSSAL,)
    elif pool=='empty':members=()
    elif pool=='unknown':
        r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,6,META));members=(UNKNOWN,)
    if pool!='missing':r.register_pool(PoolDefinition(POOL_ID,'bwonsamdi-fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=pool!='incomplete'))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
    return s


class TalanjiBwonsamdiTests(unittest.TestCase):
    def game(self,hand=None,deck=None,board=(),enemy=(),mode='normal',pool='normal',active=1,cap=10):
        hand=(CARD,BWON,P+'kill')if hand is None else hand;deck=(UNITS[4],)*8 if deck is None else deck
        players=tuple(PlayerSetup('HERO_11'if p==active else'HERO_08',hand=hand if p==active else(),deck=deck,
            board=(((WATCH,)if mode!='normal'else())+board)if p==active else enemy,
            max_mana=10,mana=10,hand_cap=cap)for p in(1,2))
        return Game.from_scenario(Scenario(players,active_player=active,seed=305,generation_context=CTX),fixture(mode,pool))
    def play(self,g,card=CARD,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==card)
        g.apply(PlayCard(p,eid,target));return eid
    def choose(self,g,key=BOONS[0]):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def body(self,g,card=BWON,p=None):
        return next(g.state.entities[i]for i in g.state.players[p or g.state.active_player].board if g.state.entities[i].card_id==card)
    def program(self,g,p=None):return material(g.state,g.registry,p or g.state.active_player,BWON)
    def portable(self,g,mode='normal',pool='normal'):
        s=g.snapshot();r=fixture.__wrapped__(mode,pool)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        return Game.from_snapshot(s,r)

    def test_complete_twelve_rows_twelve_primary_faces_and_actual_deathknight_bundle(self):
        d=load_batch();r=fixture()
        self.assertEqual((len(d['cards']),len(d['choice_only']),len(d['evidence_only']),len(d['official_observations'])),(3,3,6,12))
        self.assertEqual(r.card(CARD).metadata.classes,(CardClass.DEATH_KNIGHT,))
        self.assertEqual((r.card(CARD).cost,r.card(CARD).attack,r.card(CARD).health),(4,4,5))
        self.assertEqual(expand_fabled_cards((CARD,),r),(CARD,BWON,SPELL))
        for cid in BOONS:self.assertTrue(r.card(cid).choice_only);self.assertFalse(r.card(cid).hand_playable)

    def test_actual_root_draws_original_named_minion_then_grants_boon_before_six_mana_play(self):
        g=self.game((CARD,P+'kill'),deck=(BWON,UNITS[4]));original=g.state.players[1].deck[0]
        self.play(g);self.assertIn(original,g.state.players[1].hand);self.assertEqual(g.state.players[1].mana,6)
        self.assertEqual(g.state.pending_choice.source_id,g.state.play_history[-1].source_id)
        self.choose(g);e=g.state.entities[original];self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertEqual(self.program(g)[:2],(6,(Keyword.TAUNT,)))
        self.assertEqual(self.play(g,BWON),original);self.assertEqual(g.state.players[1].mana,0)

    def test_dead_named_minion_is_reconstructed_instead_of_drawing_an_existing_deck_copy(self):
        g=self.game((P+'kill',CARD),deck=(BWON,),board=(BWON,));old=self.body(g).id;deck_id=g.state.players[1].deck[0]
        self.play(g,P+'kill',old);self.play(g);fresh=self.body(g)
        self.assertNotEqual(fresh.id,old);self.assertIn(deck_id,g.state.players[1].deck)
        self.assertEqual((fresh.attack,fresh.max_health,fresh.damage),(6,6,0));self.choose(g,BOONS[2])
        self.assertIn(Keyword.RUSH,g.state.entities[fresh.id].keywords);self.portable(g)

    def test_enemy_death_and_burned_card_do_not_replace_friendly_death_credit(self):
        g=self.game((P+'kill',CARD),deck=(BWON,),enemy=(BWON,));enemy=self.body(g,p=2).id;original=g.state.players[1].deck[0]
        self.play(g,P+'kill',enemy);self.play(g);self.assertIn(original,g.state.players[1].hand)
        self.assertFalse(any(g.state.entities[i].card_id==BWON for i in g.state.players[1].board));self.choose(g)

    def test_missing_or_burned_draw_still_records_permanent_boon_for_future_named_copy(self):
        g=self.game((CARD,P+'get'),deck=(BWON,),mode='burn',cap=2);original=g.state.players[1].deck[0]
        self.play(g);self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD);self.assertFalse(g.state.death_history)
        self.choose(g);self.play(g,P+'get');fresh=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==BWON)
        self.assertIn(Keyword.TAUNT,fresh.keywords);self.assertNotEqual(fresh.id,original)
        g=self.game((CARD,),deck=());self.play(g);self.choose(g);self.assertEqual(self.program(g)[0],6)

    def test_three_repeated_boons_progress_cost_and_update_all_owned_named_instances(self):
        g=self.game((CARD,SPELL,SPELL),deck=(BWON,),board=(BWON,),enemy=(BWON,))
        for card in(CARD,SPELL,SPELL):self.play(g,card);self.choose(g,BOONS[0])
        self.assertEqual(self.program(g)[:2],(10,(Keyword.TAUNT,)));self.assertEqual(len(self.program(g)[2]),3)
        for e in g.state.entities.values():
            if e.card_id==BWON and e.controller==1 and e.zone in(Zone.HAND,Zone.BOARD):self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertNotIn(Keyword.TAUNT,self.body(g,p=2).keywords);self.assertEqual(self.program(g,2)[0],4)

    def test_all_three_different_boons_reach_ten_and_all_inherit_on_original_new_body(self):
        g=self.game((CARD,SPELL,SPELL,BWON,P+'kill'))
        for card,boon in zip((CARD,SPELL,SPELL),BOONS):self.play(g,card);self.choose(g,boon)
        self.assertEqual(self.program(g)[:2],(10,KEYWORDS))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,BWON);self.play(g,P+'kill',self.body(g).id)
        child=self.body(g,UNITS[10]);self.assertTrue(set(KEYWORDS)<=child.keywords)

    def test_deathrattle_inherits_only_ordinary_keywords_on_the_real_new_pool_body(self):
        g=self.game((CARD,BWON,P+'kill',P+'silence'));self.play(g);self.choose(g)
        self.play(g,BWON);self.play(g,P+'kill',self.body(g).id);child=self.body(g,UNITS[6])
        self.assertIn(Keyword.TAUNT,child.keywords);self.assertFalse(any(a.kind=='deathrattle'for a in child.abilities))
        self.play(g,P+'silence',child.id);self.assertNotIn(Keyword.TAUNT,g.state.entities[child.id].keywords)
        self.assertEqual(self.program(g)[0],6)

    def test_player_boons_do_not_follow_stolen_bwonsamdi_into_opponent_deathrattle(self):
        g=self.game((CARD,BWON,P+'give',P+'kill'));self.play(g);self.choose(g)
        self.play(g,BWON);bwon=self.body(g);self.play(g,P+'give',bwon.id)
        self.assertIn(Keyword.TAUNT,g.state.entities[bwon.id].keywords);self.play(g,P+'kill',bwon.id)
        child=self.body(g,UNITS[4],p=2);self.assertFalse(set(KEYWORDS)&child.keywords)
        self.assertEqual(self.program(g,2)[0],4);self.portable(g)

    def test_dormant_minion_receives_original_rush_before_entry_and_keeps_it_until_waking(self):
        g=self.game(pool='dormant');self.play(g);self.choose(g,BOONS[2]);self.play(g,BWON)
        self.play(g,P+'kill',self.body(g).id);child=self.body(g,DORMANT)
        self.assertIsNotNone(child.dormancy)
        self.assertTrue(any(a.kind=='keyword'and a.keyword==Keyword.RUSH for a in child.abilities))
        self.portable(g,pool='dormant')

    def test_real_colossal_accepts_native_rush_before_main_body_and_appendage_delivery(self):
        g=self.game(pool='colossal');self.play(g);self.choose(g,BOONS[2]);self.play(g,BWON)
        self.play(g,P+'kill',self.body(g).id);child=self.body(g,COLOSSAL)
        self.assertIn(Keyword.RUSH,child.keywords);self.assertTrue(g.state.colossal_history)
        self.portable(g,pool='colossal')

    def test_permanent_named_keyword_survives_silence_but_printed_deathrattle_does_not(self):
        g=self.game((CARD,BWON,P+'silence',P+'kill'));self.play(g);self.choose(g)
        self.play(g,BWON);bwon=self.body(g);self.play(g,P+'silence',bwon.id)
        self.assertIn(Keyword.TAUNT,g.state.entities[bwon.id].keywords);self.assertFalse(any(a.kind=='deathrattle'for a in g.state.entities[bwon.id].abilities))
        self.play(g,P+'kill',bwon.id);self.assertFalse(any(g.state.entities[i].card_id==UNITS[6]for i in g.state.players[1].board))

    def test_current_hand_copy_and_bounce_keep_player_program_without_duplicate_progress(self):
        g=self.game((CARD,BWON,P+'copy',P+'bounce'));self.play(g);self.choose(g)
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==BWON)
        self.play(g,P+'copy',source);self.assertEqual(len(self.program(g)[2]),1)
        for eid in g.state.players[1].hand:
            if g.state.entities[eid].card_id==BWON:self.assertIn(Keyword.TAUNT,g.state.entities[eid].keywords)
        self.play(g,BWON);bwon=self.body(g);self.play(g,P+'bounce',bwon.id)
        self.assertIn(Keyword.TAUNT,g.state.entities[bwon.id].keywords);self.assertEqual(len(self.program(g)[2]),1)

    def test_swathe_hits_both_enemy_hero_and_minions_then_chooses_without_discover(self):
        g=self.game((SPELL,),enemy=(UNITS[4],));target=g.state.players[2].board[0];self.play(g,SPELL)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.assertEqual(g.state.entities[target].damage,2)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,BOONS[1]);self.assertEqual(self.program(g)[:2],(6,(Keyword.LIFESTEAL,)))
        self.assertFalse(any(e.kind=='discovery_offered'for e in g.events))

    def test_summon_quantity_shares_frozen_entry_keywords_on_independent_physical_bodies(self):
        g=self.game(board=(P+'twice',));self.play(g);self.choose(g,BOONS[1]);self.play(g,BWON)
        self.play(g,P+'kill',self.body(g).id)
        children=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==UNITS[6]]
        self.assertEqual(len(children),2);self.assertTrue(all(Keyword.LIFESTEAL in e.keywords for e in children))

    def test_full_board_failed_resurrection_still_preserves_boon_for_original_deck_recipient(self):
        g=self.game((P+'kill',CARD),deck=(BWON,),board=(BWON,)+(UNITS[4],)*5)
        self.play(g,P+'kill',self.body(g).id);self.play(g);self.assertEqual(len(g.state.players[1].board),7)
        self.assertFalse(any(g.state.entities[i].card_id==BWON for i in g.state.players[1].board))
        self.choose(g,BOONS[2]);self.assertIn(Keyword.RUSH,g.state.entities[g.state.players[1].deck[0]].keywords)

    def test_waiting_boon_and_install_reaction_restore_independently_without_repaying(self):
        g=self.game(mode='wait');self.play(g);before=self.portable(g,'wait');self.choose(g)
        self.assertIsNotNone(g.state.pending_choice);saved=g.snapshot();restored=self.portable(g,'wait')
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.choose(restored,'ok')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.players[1].mana,6)
        self.choose(before);self.choose(before,'ok');self.assertEqual(before.snapshot(),g.snapshot())

    def test_failed_install_reaction_and_invalid_choice_restore_whole_original_boundary(self):
        g=self.game(mode='fail');self.play(g);saved=g.snapshot()
        for key,errors in((BOONS[0],ResolutionError),('unknown.boon',(IllegalAction,ResolutionError))):
            with self.subTest(key=key),self.assertRaises(errors):self.choose(g,key)
            self.assertEqual(g.snapshot(),saved)

    def test_missing_unknown_pool_rollback_and_formal_incomplete_pool_rejection(self):
        # Experimental inventories may deliberately be partial; formal ones cannot.
        with self.assertRaises(ValueError):
            PoolDefinition(POOL_ID,'incomplete-standard',CTX.target_id,'standard',(),complete=False)
        for pool in('missing','unknown'):
            with self.subTest(pool=pool):
                g=self.game(pool=pool);self.play(g);self.choose(g);self.play(g,BWON);saved=g.snapshot();target=self.body(g).id
                with self.assertRaises(ResolutionError):self.play(g,P+'kill',target)
                self.assertEqual(g.snapshot(),saved)

    def test_confirmed_empty_complete_pool_does_not_create_replacement_or_use_rng(self):
        g=self.game(pool='empty');self.play(g);self.choose(g);self.play(g,BWON);rng=g._rng.getstate()
        self.play(g,P+'kill',self.body(g).id);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(len(g.state.players[1].board),1)

    def test_hidden_boon_choices_and_programs_do_not_change_opponent_observation(self):
        games=[]
        for boon in(BOONS[0],BOONS[1]):
            g=self.game((CARD,),deck=(BWON,));self.play(g);self.choose(g,boon);games.append(g)
            public=json.dumps(g.observe(2));self.assertTrue(all(cid not in public for cid in BOONS))
            self.assertNotIn('boon_summon_cost',public);self.assertNotIn('instance_json',public)
            self.assertEqual(len(g.observe(1)['players'][0]['player_effects']),1)
            self.assertEqual(g.observe(1)['players'][0]['hand'][0]['boon_summon_cost'],6)
        self.assertEqual(games[0].observe(2),games[1].observe(2))

    def test_rehashed_program_or_acceptance_crop_and_wrong_actor_are_rejected(self):
        g=self.game();self.play(g);self.choose(g);saved=g.snapshot()
        bad=deepcopy(saved);bad['state']['players']['1']['player_effects']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())
        index=next(i for i,e in enumerate(g.events)if e.kind==ACCEPTED)
        bad=deepcopy(saved);bad['events'][index]['player_id']=2
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())
        recipient=next(e for e in g.state.entities.values()if e.card_id==BWON and e.controller==1 and e.zone==Zone.HAND)
        bad=deepcopy(saved);row=bad['state']['entities'][str(recipient.id)]
        row['abilities']=[a for a in row['abilities']if not(a['kind']=='keyword'and a['keyword']=='taunt')]
        # A stale keyword cache must not let refresh silently recreate cropped material.
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture())

    def test_second_actor_owns_permanent_program_and_named_current_body(self):
        g=self.game(active=2);self.play(g);self.choose(g,BOONS[1]);self.play(g,BWON)
        self.assertEqual(self.program(g,1)[0],4);self.assertEqual(self.program(g,2)[0],6)
        self.assertIn(Keyword.LIFESTEAL,self.body(g,p=2).keywords)

    def test_only_canonical_actual_boon_keyword_recipes_extend_pool_entry(self):
        for mask in range(8):validate_pool_entry_keywords(tuple(k for i,k in enumerate(KEYWORDS)if mask&(1<<i)))
        for value in((Keyword.RUSH,Keyword.TAUNT),(Keyword.TAUNT,Keyword.TAUNT),(Keyword.CHARGE,),['rush']):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_pool_entry_keywords(value)

    def test_actual_fabled_builder_and_opening_keep_exact_original_two_companions(self):
        r=fixture();cards=expand_fabled_cards((CARD,)+(UNITS[4],)*9,r)
        policy=DeckPolicy('bwonsamdi.opening',CTX.target_id,CTX.mode,(CARD,BWON,SPELL,UNITS[4]),deck_size=12,max_copies=12)
        setup=MatchSetup(tuple(DeckSpec('HERO_11','HERO_11bp',CardClass.DEATH_KNIGHT,cards,Runes(1,1,1))for _ in(1,2)),
            policy,'GAME_005',seed=305,first_player=1)
        g=Game.from_decks(setup,r)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        for p in(1,2):
            self.assertEqual(g.state.players[p].original_deck.count(BWON),1)
            self.assertEqual(g.state.players[p].original_deck.count(SPELL),1)
        self.portable(g)


if __name__=='__main__':unittest.main()
