"""Seven current stat/draw cards and captured random-target continuations."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.stat_draw_cards import load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CastWhenDrawnSpec,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import CostSpec, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_sequences import DrawIfCheap
from hs_sim.engine.spell_targets import ApplySpellTarget, RandomSpellTarget
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r=build_registry()
    meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    for name,attack,health,cost,extra in (
        ('big',2,12,4,{}),('high',8,8,3,{}),('cheap',1,4,2,{}),
        ('shield',2,8,3,dict(keywords=(Keyword.DIVINE_SHIELD,))),
        ('immune',10,8,3,dict(keywords=(Keyword.IMMUNE,))),
        ('sleep',20,8,3,dict(dormant_turns=2)),
        ('undead',2,5,2,dict(metadata=replace(meta,tribes=('undead',)))),
        ('bonus',1,1,2,dict(spell_damage=1)),
    ):
        values=dict(metadata=meta);values.update(extra)
        r.register_card(CardDefinition('k18.'+name,name,CardType.MINION,attack=attack,health=health,cost=cost,**values))
    scripts={
        'noop':lambda c:(),
        'wound':lambda c:(Damage(c.state.players[1].hero_id,12,c.source_id),),
        'hit':lambda c:(Damage(c.target_id,3,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'cap':lambda c:(SetHandCapacity(c.player_id,1),),
        'cut':lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),
            CostSpec(delta=-3),c.source_id),),
        'fail':lambda c:(AddToHand(c.player_id,'missing.k18'),),
        'auto':lambda c:(GainArmor(c.player_id,2),),
    }
    for name,body in scripts.items():r.register_behavior('k18.'+name,body)
    for name in ('noop','wound','hit','silence','cap','cut'):
        r.register_card(CardDefinition('k18.'+name,name,CardType.SPELL,on_play='k18.'+name,
            requires_target=name in ('hit','silence'),metadata=meta))
    for name,cost in (('auto',1),('auto_big',7)):
        r.register_card(CardDefinition('k18.'+name,name,CardType.SPELL,cost=cost,on_play='k18.auto',
            keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(),metadata=meta))
    if mode:
        def watch(c):
            if c.state.entities[c.state.players[1].hero_id].armor:return ()
            expected='JAIL_377' if mode=='draw' else ('CORE_RLK_087' if mode=='destroy' else 'EDR_255')
            if c.state.entities[c.event.source_id].card_id != expected:return ()
            if mode=='draw':
                options=(ChoiceOption('ok','Extra draw',(GainArmor(1,1),DrawIfCheap(1,0,c.source_id))),)
            else:
                entity=c.state.entities[c.event.target_id]
                other=next(eid for eid in c.state.players[entity.controller].board if eid != entity.id)
                options=(
                    ChoiceOption('ok','Keep original selection',(GainArmor(1,1),Buff(other,attack=20))),
                    ChoiceOption('cycle','Return then summon same physical minion',(
                        ReturnToHand(entity.id),SummonFromZone(entity.controller,zone=Zone.HAND,
                            selection='first',source_id=c.source_id),GainArmor(1,1))),
                )
            return (RequestChoice(1,(*options,
                ChoiceOption('bad','Rollback',(InvokeBehavior('k18.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('k18.watch',watch)
        r.register_card(CardDefinition('k18.watch','Observer',CardType.MINION,health=20,metadata=meta,
            triggers=(TriggerSpec('card_drawn' if mode=='draw' else 'random_choice','k18.watch'),)))
    return r


class StatDrawCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=('k18.noop',)*5,mode=None,hero='HERO_08'):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',board=enemy,deck=('k18.noop',)*5)),seed=263),registry(mode) if mode else self.registry)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def rows(self,g,cid):return [r.health_result for r in g.state.damage_history if r.health_result.source_card_id==cid]

    def test_seven_full_source_records_and_lifesteal(self):
        self.assertEqual(len(load_batch()['cards']),7)
        for row in load_batch()['cards']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            card=self.registry.card(row['record']['id']);self.assertEqual(card.cost,row['record']['cost'])
            self.assertEqual(Keyword.LIFESTEAL in card.keywords,row['record']['tags'].get('LIFESTEAL')==1)

    def test_equality_sets_both_current_health_and_max_without_damage_and_silence_restores(self):
        g=self.game(('k18.hit','CORE_EX1_619','k18.silence'),board=('k18.big',),enemy=('k18.big',))
        own=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
        self.play(g,'k18.hit',enemy);self.play(g,'CORE_EX1_619')
        for eid in (own,enemy):self.assertEqual((g.state.entities[eid].health,g.state.entities[eid].max_health),(1,1))
        self.assertFalse(self.rows(g,'CORE_EX1_619'))
        self.play(g,'k18.silence',enemy);self.assertEqual(g.state.entities[enemy].health,12)

    def test_equality_does_not_hit_heroes_dormant_or_consume_shield(self):
        g=self.game(('CORE_EX1_619',),enemy=('k18.shield','k18.sleep'))
        shield,sleep=g.state.players[2].board;self.play(g,'CORE_EX1_619')
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[shield].keywords)
        self.assertEqual(g.state.entities[sleep].health,8)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_asphyxiate_highest_attack_skips_dormant_and_has_no_single_rng(self):
        g=self.game(('CORE_RLK_087',),enemy=('k18.big','k18.high','k18.sleep'))
        high=g.state.players[2].board[1];before=g.snapshot()['rng_state'];self.play(g,'CORE_RLK_087')
        self.assertEqual(g.state.entities[high].zone,Zone.GRAVEYARD)
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertFalse(any(e.kind=='random_choice' for e in g.events))

    def test_asphyxiate_tie_selects_once_and_keeps_original_after_other_becomes_highest(self):
        g=self.game(('CORE_RLK_087',),board=('k18.watch',),enemy=('k18.high','k18.high'),mode='destroy')
        self.play(g,'CORE_RLK_087');self.assertIsNotNone(g.state.pending_choice)
        events=[e for e in g.events if e.kind=='random_choice'];self.assertEqual(len(events),1)
        target=events[0].target_id;other=self.portable(g,'destroy')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        survivor=g.state.entities[g.state.players[2].board[0]];self.assertEqual(survivor.attack,28)

    def test_asphyxiate_waiting_cycle_same_id_is_not_new_target_and_bad_selection_rolls_back(self):
        g=self.game(('CORE_RLK_087',),board=('k18.watch',),enemy=('k18.high','k18.high'),mode='destroy')
        self.play(g,'CORE_RLK_087');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        target=next(e.target_id for e in g.events if e.kind=='random_choice')
        other=self.portable(g,'destroy')
        for current in (g,other):self.choose(current,'cycle')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[2].board),2)
        self.assertIn(target,g.state.players[2].board);self.assertFalse(g.state.death_history)

    def test_asphyxiate_empty_and_immune_use_shared_destroy(self):
        empty=self.game(('CORE_RLK_087',));self.play(empty,'CORE_RLK_087');self.assertFalse(empty.state.death_history)
        g=self.game(('CORE_RLK_087',),enemy=('k18.immune',))
        self.play(g,'CORE_RLK_087');self.assertFalse(g.state.players[2].board)

    def test_flames_fresh_lowest_targets_lifesteal_and_actual_damage(self):
        g=self.game(('k18.wound','EDR_255'),enemy=('k18.cheap','k18.high'))
        self.play(g,'k18.wound');self.play(g,'EDR_255')
        self.assertEqual([r.target_card_id for r in self.rows(g,'EDR_255')],['k18.cheap','k18.high'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,3)

    def test_flames_with_only_hero_hits_twice_and_shield_prevents_lifesteal(self):
        g=self.game(('k18.wound','EDR_255'));self.play(g,'k18.wound');self.play(g,'EDR_255')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,20)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
        g=self.game(('k18.wound','EDR_255'),enemy=('k18.shield',))
        self.play(g,'k18.wound');self.play(g,'EDR_255')
        self.assertEqual([r.damage_dealt for r in self.rows(g,'EDR_255')],[0,5])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,23)

    def test_flames_requeries_current_spell_damage_and_dormant_not_candidate(self):
        g=self.game(('EDR_255',),board=('k18.bonus',),enemy=('k18.sleep',))
        self.play(g,'EDR_255')
        self.assertEqual([r.damage_dealt for r in self.rows(g,'EDR_255')],[6,6])
        self.assertTrue(all(r.target_kind=='hero' for r in self.rows(g,'EDR_255')))

    def test_flames_random_waiting_cycle_guard_and_second_independent_acceptance(self):
        g=self.game(('EDR_255',),board=('k18.watch',),enemy=('k18.high','k18.high'),mode='damage')
        self.play(g,'EDR_255');target=next(e.target_id for e in g.events if e.kind=='random_choice')
        other=self.portable(g,'damage')
        for current in (g,other):self.choose(current,'cycle')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.rows(g,'EDR_255')),1)
        self.assertEqual(len([e for e in g.events if e.kind=='random_choice']),2)
        self.assertIn(target,g.state.players[2].board)
        public=json.dumps(g.observe(2))+json.dumps(g.player_events(2))
        self.assertNotIn('MinionReference',public);self.assertNotIn('cast_history',public)

    def test_barrier_shields_hero_and_buffs_only_current_held_minions(self):
        g=self.game(('TIME_447','k18.cheap','k18.noop'),board=('k18.big',))
        hero=g.state.players[1].hero_id;self.play(g,'TIME_447',hero)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[hero].keywords)
        held=next(g.state.entities[e] for e in g.state.players[1].hand if g.state.entities[e].card_id=='k18.cheap')
        self.assertEqual(held.max_health,6);self.assertEqual(g.state.entities[g.state.players[1].board[0]].max_health,12)
        self.portable(g)

    def test_barrier_target_required_and_invalid_target_transaction_unchanged(self):
        g=self.game(('TIME_447',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'TIME_447')
        self.assertEqual(g.snapshot(),before)

    def test_legacy_hero_attack_expires_hand_attack_is_permanent_and_deck_is_physical(self):
        g=self.game(('TIME_449','k18.cheap'),deck=('k18.noop',))
        self.play(g,'TIME_449');hero=g.state.players[1].hero_id;held=g.state.players[1].hand[0]
        self.assertEqual(g.state.entities[hero].attack,4);self.assertEqual(g.state.entities[held].attack,5)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[hero].attack,0)
        self.assertEqual(g.state.entities[held].attack,5)
        g=self.game(('TIME_449','k18.cheap'),deck=('k18.cheap',))
        self.play(g,'TIME_449');self.assertEqual(g.state.entities[g.state.players[1].hand[0]].attack,1)

    def test_legacy_empty_deck_qualifies_and_no_held_minion_is_not_error(self):
        g=self.game(('TIME_449',),deck=());self.play(g,'TIME_449')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,4)

    def test_bola_first_cheap_or_expensive_does_not_recurse_and_stored_reduction_counts(self):
        for deck,count in ((('k18.cheap','k18.cheap','k18.cheap'),2),(('k18.high','k18.cheap'),1)):
            g=self.game(('JAIL_377',),deck=deck);self.play(g,'JAIL_377');self.assertEqual(len(g.state.draw_history),count)
        g=self.game(('k18.cut','JAIL_377'),deck=('k18.big','k18.big'))
        self.play(g,'k18.cut');self.play(g,'JAIL_377');self.assertEqual(len(g.state.draw_history),2)

    def test_bola_cast_replacement_never_becomes_original_cost_subject(self):
        for first,count in (('k18.auto',3),('k18.auto_big',2)):
            g=self.game(('JAIL_377',),deck=(first,'k18.cheap','k18.cheap'))
            self.play(g,'JAIL_377');self.assertEqual(len(g.state.draw_history),count)
            self.assertEqual(g.state.draw_history[0].outcome,'cast');self.portable(g)

    def test_bola_fatigue_no_subject_and_burn_retains_original_price_condition(self):
        g=self.game(('JAIL_377',),deck=());self.play(g,'JAIL_377')
        self.assertEqual([r.outcome for r in g.state.draw_history],['fatigue'])
        g=self.game(('k18.cap','JAIL_377','k18.big'),deck=('k18.cheap','k18.cheap'))
        self.play(g,'k18.cap');self.play(g,'JAIL_377')
        self.assertEqual([r.outcome for r in g.state.draw_history],['burned','burned'])

    def test_bola_draw_waiting_quote_and_new_extra_draw_do_not_change_first_condition(self):
        for original,count in (('k18.cheap',3),('k18.high',2)):
            g=self.game(('JAIL_377',),board=('k18.watch',),deck=(original,'k18.high','k18.high'),mode='draw')
            self.play(g,'JAIL_377');self.assertIsNotNone(g.state.pending_choice)
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(g.snapshot(),before);other=self.portable(g,'draw')
            for current in (g,other):self.choose(current)
            self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),count)

    def test_finality_tutors_actual_undead_then_imbues_twice(self):
        g=self.game(('END_003',),deck=('k18.big','k18.undead','k18.noop'),hero='HERO_11')
        self.play(g,'END_003')
        self.assertEqual([r.card_id for r in g.state.draw_history],['k18.undead'])
        self.assertEqual(len(g.state.imbue_history),2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'END_003p')
        self.portable(g)

    def test_finality_no_matching_or_empty_still_imbues_and_no_fatigue(self):
        for deck in ((),('k18.big',)):
            g=self.game(('END_003',),deck=deck,hero='HERO_11');self.play(g,'END_003')
            self.assertFalse(g.state.draw_history);self.assertEqual(len(g.state.imbue_history),2)

    def test_captured_spell_typed_contract_rejects_duplicate_targets_and_hero_destroy(self):
        g=self.game(enemy=('k18.high',));ref=MinionReference.capture(g.state.entities[g.state.players[2].board[0]])
        for factory in (lambda:RandomSpellTarget((ref,ref),1,'damage',5),
                        lambda:ApplySpellTarget(g.state.players[2].hero_id,1,'destroy'),
                        lambda:ApplySpellTarget(ref,1,'invented'),lambda:DrawIfCheap(1,-1,1)):
            with self.assertRaises(ValueError):factory()
