"""Real Smoldering spell values, original hand progression and true discard."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.burning_hand_spell_cards import (STRENGTH,ASCENT,load_batch,
                                                  register_burning_hand_spell_cards)
from hs_sim.cards.held_draw_cards import register_held_draw_cards
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Registry,Scenario,SelectChoice,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.effects import AddToHand,ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.targets import canonical_digest

P='k204.'
HERO,A,B,SMALL,DORMANT,SHIELD,POWER,EMPTY,WATCH=(P+x for x in
    ('hero','a','b','small','dormant','shield','power','empty','watch'))


@lru_cache(None)
def registry(mode=None):
    r=Registry(P+str(mode));register_held_draw_cards(r);register_burning_hand_spell_cards(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=60))
    for cid,atk,hp in ((A,1,6),(B,2,8),(SMALL,0,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=atk,health=hp))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=9,dormant_turns=2))
    r.register_card(CardDefinition(SHIELD,SHIELD,CardType.MINION,health=2,keywords=(Keyword.DIVINE_SHIELD,)))
    r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=20,spell_damage=2))
    r.register_behavior(P+'empty',lambda c:())
    r.register_card(CardDefinition(EMPTY,EMPTY,CardType.SPELL,on_play=P+'empty'))
    r.register_behavior(P+'fail',lambda c:(_ for _ in ()).throw(ResolutionError('K204 deliberate failure')))
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    def roundtrip(c):
        card=ref(c)
        return(MoveCard(card,c.player_id,Zone.DECK,source_id=c.source_id),
            MoveCard(replace(card,zone=Zone.DECK,zone_epoch=card.zone_epoch+1),c.player_id,Zone.HAND,source_id=c.source_id))
    def pull(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].deck
               if c.state.entities[i].card_id in(STRENGTH,ASCENT))
        return(MoveCard(CardReference.capture(e),c.player_id,Zone.HAND,source_id=c.source_id),)
    scripts=dict(
        current=lambda c:(CopyCard(ref(c),c.player_id,mode='current',source_id=c.source_id),),
        base=lambda c:(CopyCard(ref(c),c.player_id,mode='base',source_id=c.source_id),),
        stash=lambda c:(MoveCard(ref(c),c.player_id,Zone.DECK,source_id=c.source_id),),
        give=lambda c:(MoveCard(ref(c),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        roundtrip=roundtrip,pull=pull,
        add=lambda c:(AddToHand(c.player_id,STRENGTH,c.source_id),),
        auto=lambda c:(CastSpell(c.player_id,ASCENT,c.source_id),))
    for name,body in scripts.items():
        r.register_behavior(P+name,body)
        fields={}if name in('pull','add','auto')else dict(targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,)))
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,**fields))
    def watch(c):
        e=c.state.entities.get(c.event.target_id)
        if e is None or e.card_id not in(STRENGTH,ASCENT):return ()
        options=[ChoiceOption('ok','Continue'),
                 ChoiceOption('bad','Rollback',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))]
        if e.zone==Zone.HAND:
            options.append(ChoiceOption('stash','Move original to deck',(
                MoveCard(CardReference.capture(e),c.player_id,Zone.DECK,source_id=c.source_id),)))
            options.append(ChoiceOption('add','Add new spell',(AddToHand(c.player_id,STRENGTH,c.source_id),)))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(P+'watch',watch)
    event={'progress':'hand_progressed','discard':'card_discarded'}.get(mode)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,
        triggers=()if event is None else(TriggerSpec(event,P+'watch'),)))
    r.validate();return r


class BurningHandSpellTests(unittest.TestCase):
    def game(self,hand=(STRENGTH,ASCENT),board=(A,),enemy=(B,),actor=1,mode=None):
        self.mode=mode
        own=PlayerSetup(HERO,hand=hand,board=board,deck=(EMPTY,)*16,mana=80,max_mana=80,mana_cap=80)
        other=PlayerSetup(HERO,board=enemy,deck=(EMPTY,)*16,mana=80,max_mana=80,mana_cap=80)
        return Game.from_scenario(Scenario((own,other)if actor==1 else(other,own),
            active_player=actor,seed=204),registry(mode))

    def eid(self,g,cid,zone='hand',player=None):
        p=g.state.active_player if player is None else player
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None,entity=None):
        eid=self.eid(g,cid)if entity is None else entity
        g.apply(PlayCard(g.state.active_player,eid,target));return eid

    def end(self,g,n=1):
        for _ in range(n):g.apply(EndTurn(g.state.active_player))

    def age(self,g,eid):return progress_ability(g.state.entities[eid]).progress_completions

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=registry.__wrapped__(self.mode)
        self.assertEqual(Game.from_snapshot(deepcopy(s),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)

    def test_two_original_spells_one_evidence_row_four_primary_faces(self):
        d=load_batch();self.assertEqual([r['record']['id']for r in d['cards']],[STRENGTH,ASCENT])
        self.assertEqual([r['record']['id']for r in d['evidence_only']],['FIR_914e'])
        self.assertEqual(len(d['official_observations']),4)
        for row in d['cards']+d['evidence_only']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertNotIn('FIR_914e',registry().cards)

    def test_initial_strength_costs_one_and_buffs_only_friendly_minion(self):
        g=self.game();target=self.eid(g,A,'board');source=self.play(g,STRENGTH,target)
        self.assertEqual((g.state.players[1].mana,g.state.entities[target].attack,g.state.entities[target].max_health),(79,2,7))
        self.assertFalse(g.state.discard_history);self.assertEqual(g.state.cast_history[-1].source_id,source)

    def test_strength_rejects_hero_enemy_and_missing_target_before_payment(self):
        for target_kind in ('hero','enemy','missing'):
            g=self.game();target=g.state.players[1].hero_id if target_kind=='hero'else self.eid(g,B,'board',2)if target_kind=='enemy'else None
            before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,STRENGTH,target)
            self.assertEqual(g.snapshot(),before)

    def test_strength_grows_after_one_and_two_held_owner_ends(self):
        for ends in (1,2):
            g=self.game();self.end(g,ends*2);target=self.eid(g,A,'board')
            self.play(g,STRENGTH,target)
            self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(2+ends,7+ends))
            self.assertFalse(g.state.discard_history)

    def test_initial_ascent_costs_two_and_excludes_own_board_and_both_heroes(self):
        g=self.game();enemy=self.eid(g,B,'board',2);own=self.eid(g,A,'board')
        self.play(g,ASCENT)
        self.assertEqual((g.state.players[1].mana,g.state.entities[enemy].health,g.state.entities[own].health),(78,7,6))
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[60,60])

    def test_ascent_grows_and_ordinary_spell_damage_applies_once(self):
        g=self.game(board=(A,POWER));self.end(g,4);target=self.eid(g,B,'board',2)
        self.play(g,ASCENT);self.assertEqual(g.state.entities[target].health,3)
        self.portable(g)

    def test_spell_damage_does_not_increase_strengths_stats(self):
        g=self.game(board=(A,POWER));target=self.eid(g,A,'board')
        self.play(g,STRENGTH,target)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(2,7))

    def test_ascent_respects_dormancy_and_divine_shield(self):
        g=self.game(enemy=(DORMANT,SHIELD,B))
        dormant=self.eid(g,DORMANT,'board',2);shield=self.eid(g,SHIELD,'board',2)
        self.play(g,ASCENT)
        self.assertEqual((g.state.entities[dormant].health,g.state.entities[shield].health),(9,2))
        self.assertFalse(any(a.keyword==Keyword.DIVINE_SHIELD for a in active_abilities(g.state.entities[shield],'keyword')))

    def test_ascent_empty_board_and_automatic_base_cast_use_normal_spell_flow(self):
        g=self.game((ASCENT,),enemy=());self.play(g,ASCENT)
        self.assertEqual(g.state.players[1].mana,78)
        g=self.game((P+'auto',));target=self.eid(g,B,'board',2)
        self.play(g,P+'auto');self.assertEqual(g.state.entities[target].health,7)
        self.assertEqual(sum(c.card_id==ASCENT for c in g.state.cast_history),1)

    def test_ascent_lethal_targets_share_one_death_batch(self):
        g=self.game((ASCENT,),enemy=(SMALL,SMALL));self.play(g,ASCENT)
        self.assertEqual(len(g.state.death_history),2)
        self.assertEqual(len({r.batch for r in g.state.death_history}),1)

    def test_third_owner_end_is_real_discard_of_each_original_spell(self):
        g=self.game();original=set(g.state.players[1].hand)
        self.end(g,4);self.assertFalse(g.state.discard_history)
        self.end(g)
        self.assertEqual({r.entity_id for r in g.state.discard_history},original)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in original))
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind=='card_destroyed_in_hand'for e in g.events))
        self.portable(g)

    def test_second_player_tracks_only_its_own_real_ends(self):
        g=self.game(actor=2);spell=self.eid(g,STRENGTH)
        self.end(g);self.assertEqual(self.age(g,spell),1)
        self.end(g);self.assertEqual(self.age(g,spell),1)
        self.end(g,3);self.assertEqual(g.state.entities[spell].zone,Zone.GRAVEYARD)
        self.assertEqual({r.player_id for r in g.state.discard_history},{2})

    def test_current_and_base_copies_have_independent_retained_and_fresh_growth(self):
        g=self.game((STRENGTH,P+'current',P+'base'));spell=self.eid(g,STRENGTH)
        self.end(g,2);self.play(g,P+'current',spell);self.play(g,P+'base',spell)
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==STRENGTH]
        self.assertEqual([self.age(g,i)for i in ids],[1,1,0])
        self.end(g,3)
        self.assertEqual([g.state.entities[i].zone for i in ids],[Zone.GRAVEYARD,Zone.GRAVEYARD,Zone.HAND])
        self.portable(g)

    def test_deck_pauses_growth_and_ordinary_reentry_keeps_count_with_new_identity(self):
        g=self.game((STRENGTH,P+'stash',P+'pull'));spell=self.eid(g,STRENGTH)
        self.end(g,2);old=progress_ability(g.state.entities[spell]).id
        self.play(g,P+'stash',spell);self.end(g,4)
        self.assertEqual(self.age(g,spell),1);self.play(g,P+'pull')
        self.assertNotEqual(progress_ability(g.state.entities[spell]).id,old)
        self.end(g);self.assertEqual(self.age(g,spell),2)

    def test_handed_over_spell_uses_current_holder_ends_and_discard_owner(self):
        g=self.game((STRENGTH,P+'give'));spell=self.eid(g,STRENGTH)
        self.end(g,2);self.play(g,P+'give',spell);self.end(g)
        self.assertEqual(self.age(g,spell),1)
        self.end(g,3)
        self.assertEqual(g.state.entities[spell].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.discard_history[0].player_id,2)

    def test_actual_grove_and_both_new_spells_follow_same_independent_family_progress(self):
        g=self.game((STRENGTH,ASCENT,'FIR_911'));original=set(g.state.players[1].hand)
        self.end(g,4);self.assertEqual([self.age(g,i)for i in original],[2,2,2])
        self.end(g);self.assertEqual({r.entity_id for r in g.state.discard_history},original)

    def test_progress_waiting_restores_original_counts_and_does_not_add_new_card_to_end(self):
        g=self.game(board=(A,WATCH),mode='progress');spell=self.eid(g,STRENGTH)
        self.end(g);self.assertEqual(self.age(g,spell),1);self.portable(g)
        self.choose(g,'add');later=g.state.players[1].hand[-1]
        self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        self.assertEqual(self.age(g,later),0);self.portable(g)

    def test_progress_choice_failure_restores_original_waiting(self):
        g=self.game((STRENGTH,),board=(A,WATCH),mode='progress');self.end(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g)

    def test_third_progress_reaction_moving_source_does_not_rebind_self_discard(self):
        g=self.game((STRENGTH,),board=(A,WATCH),mode='progress');spell=self.eid(g,STRENGTH)
        self.end(g);self.choose(g);self.end(g,2);self.choose(g);self.end(g,2)
        self.choose(g,'stash')
        self.assertEqual(g.state.entities[spell].zone,Zone.DECK)
        self.assertFalse(g.state.discard_history);self.portable(g)

    def test_each_actual_discard_wait_restores_remaining_original_sources(self):
        g=self.game(board=(A,WATCH),mode='discard');self.end(g,5)
        for _ in range(2):
            self.assertIsNotNone(g.state.pending_choice);self.portable(g)
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(g.snapshot(),before);self.choose(g)
        self.assertEqual(len(g.state.discard_history),2)

    def test_player_queries_do_not_expose_progress_receipts_or_mutate_rng(self):
        g=self.game();self.end(g,2);before=g.snapshot()
        for player in(1,2):
            visible=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for key in('progress_keys','progress_units','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',visible)
            g.for_player(player).legal_actions()
        self.assertEqual(g.snapshot(),before)
