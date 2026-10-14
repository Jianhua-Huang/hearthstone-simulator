"""Adjacent auras and atomically modified generated cards, with real Herald fixtures."""
from hs_sim.engine.model import CostAuraSpec
import json
import unittest
from dataclasses import replace

from hs_sim.engine import (AuraSpec, CardDefinition, CardType, EndTurn, Game, Herald,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, GainArmor, GrantAura, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.costs import local_cost, quote_cost
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.model import AbilityInstance, CardClass, CardMetadata, CostSpec, PaymentType
from hs_sim.engine.pools import GenerateFromPool, GenerationContext, PoolQuery
from hs_sim.engine.representative import build_registry, HERALD_POOL_ID, HERALD_POOL_IDS
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard


CONTEXT = GenerationContext('local-2026-09-23', 'experimental')


class HeraldExtensionTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        for cls in (CardClass.SHAMAN, CardClass.ROGUE, CardClass.DEATH_KNIGHT):
            self.r.register_card(CardDefinition(cls.value, cls.value, CardType.HERO, health=30,
                metadata=CardMetadata(False, (cls,), None)))
        self.r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=2, health=5))
        self.r.register_card(CardDefinition('aura', 'Aura', CardType.MINION, attack=1, health=3,
            auras=(AuraSpec(2, health=2, adjacent_only=True),)))
        self.r.register_card(CardDefinition('sleep', 'Sleep', CardType.MINION, attack=1, health=3, dormant_turns=None))
        self.r.register_behavior('noop', lambda c: [])
        self.r.register_card(CardDefinition('site', 'Site', CardType.LOCATION, durability=2, on_use='noop'))
        self.spell('herald', lambda c: [Herald(c.player_id, c.source_id)])
        for n in (2, 4):
            self.spell(f'prepare{n}', lambda c, n=n: [*[Herald(c.player_id, c.source_id) for _ in range(n)],
                *[Destroy(i) for i in c.state.players[c.player_id].board]])
        self.spell('kill', lambda c: [Destroy(c.target_id)], requires_target=True)
        self.spell('silence', lambda c: [Silence(c.target_id)], requires_target=True)
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)], requires_target=True)
        self.spell('copy', lambda c: [CopyMinion(c.target_id, 1)], requires_target=True)
        self.spell('steal', lambda c: [ChangeControl(c.target_id, 2)], requires_target=True)

    def spell(self, name, fn, **kw):
        self.r.register_behavior(name, fn)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kw))

    def game(self, hand=(), board=(), hero=CardClass.SHAMAN, context=CONTEXT, enemy_board=()):
        return Game.from_scenario(Scenario((PlayerSetup(hero.value, hand=hand, board=board,
            deck=('plain',)*10, max_mana=10, mana=10), PlayerSetup('HERO_01', board=enemy_board,
            deck=('plain',)*10, max_mana=10, mana=10)), generation_context=context, seed=71), self.r)

    def play(self, g, card, target=None, position=None):
        p = g.state.active_player
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == card)
        g.apply(PlayCard(p, i, target, position)); return i

    def ranked(self, n, *, hero=CardClass.SHAMAN, hand=()):
        if n == 0:
            return self.game(hero=hero, hand=hand)
        g = self.game(hero=hero, hand=(f'prepare{n}', *hand), board=('plain',)*7)
        self.play(g, f'prepare{n}')
        return g

    def board(self, g, p=1):
        return [g.state.entities[i] for i in g.state.players[p].board]

    def check(self, g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_adjacent_aura_targets_only_immediate_minions(self):
        g = self.game(board=('plain', 'aura', 'plain', 'plain'), enemy_board=('plain',))
        self.assertEqual([(e.attack, e.health) for e in self.board(g)], [(4,7),(1,3),(4,7),(2,5)])
        self.assertEqual(self.board(g, 2)[0].attack, 2); self.check(g)

    def test_locations_block_adjacency(self):
        g = self.game(board=('aura', 'site', 'plain'))
        self.assertEqual(self.board(g)[2].attack, 2); self.check(g)

    def test_dormant_occupant_blocks_and_receives_no_aura(self):
        g = self.game(board=('aura', 'sleep', 'plain'))
        self.assertEqual([e.attack for e in self.board(g)], [1,1,2]); self.check(g)

    def test_insertion_recomputes_neighbors(self):
        g = self.game(board=('aura','plain','plain'), hand=('plain',))
        self.play(g,'plain',position=1)
        self.assertEqual([e.attack for e in self.board(g)],[1,4,2,2]); self.check(g)

    def test_removing_neighbor_closes_gap(self):
        g = self.game(board=('aura','plain','plain'), hand=('kill',))
        old=self.board(g)[2].id; self.play(g,'kill',self.board(g)[1].id)
        self.assertEqual(g.state.entities[old].attack,4); self.check(g)

    def test_silence_removes_neighbor_aura(self):
        g=self.game(board=('aura','plain'),hand=('silence',))
        self.play(g,'silence',self.board(g)[0].id)
        self.assertEqual((self.board(g)[1].attack,self.board(g)[1].health),(2,5)); self.check(g)

    def test_control_change_relocates_aura(self):
        g=self.game(board=('aura','plain'),enemy_board=('plain',),hand=('steal',))
        self.play(g,'steal',self.board(g)[0].id)
        self.assertEqual(self.board(g)[0].attack,2); self.assertEqual(self.board(g,2)[0].attack,4); self.check(g)

    def test_dormancy_disables_then_restores_source(self):
        self.spell('sleep_source',lambda c:[MakeDormant(c.target_id,None)],requires_target=True)
        self.spell('wake',lambda c:[AwakenMinion(c.state.players[1].board[0])])
        g=self.game(board=('aura','plain'),hand=('sleep_source','wake'))
        self.play(g,'sleep_source',self.board(g)[0].id); self.assertEqual(self.board(g)[1].attack,2)
        self.play(g,'wake'); self.assertEqual(self.board(g)[1].attack,4); self.check(g)

    def test_health_loss_clamps_without_healing_damage(self):
        self.spell('hit',lambda c:[Damage(c.state.players[1].board[1],3)])
        g=self.game(board=('aura','plain'),hand=('hit','silence'))
        self.play(g,'hit'); self.assertEqual(self.board(g)[1].health,4)
        self.play(g,'silence',self.board(g)[0].id)
        self.assertEqual((self.board(g)[1].max_health,self.board(g)[1].health),(5,4)); self.check(g)

    def test_granted_adjacent_aura_expires(self):
        self.spell('grant',lambda c:[GrantAura(c.state.players[1].board[0],3,adjacent_only=True,expires_turn=c.state.turn)])
        g=self.game(board=('plain','plain','plain'),hand=('grant',))
        self.play(g,'grant'); self.assertEqual([e.attack for e in self.board(g)],[2,5,2])
        g.apply(EndTurn(1)); self.assertEqual([e.attack for e in self.board(g)],[2,2,2]); self.check(g)

    def test_invalid_adjacency_declarations_are_rejected(self):
        for value in (1,'adjacent',None):
            with self.assertRaises(ValueError): GrantAura(1,adjacent_only=value)
            with self.assertRaises(ValueError): AbilityInstance(1,'aura',adjacent_only=value)
        with self.assertRaises(ValueError): GrantAura(1,include_self=True,adjacent_only=True)
        with self.assertRaises(ValueError): AbilityInstance(1,'spell_damage',spell_damage=1,adjacent_only=True)
        with self.assertRaises(ValueError): self.r.register_card(CardDefinition('bad','Bad',CardType.MINION,health=1,
            auras=(AuraSpec(1,include_self=True,adjacent_only=True),)))

    def test_shaman_source_gets_soldier_neighbor_bonus(self):
        g=self.game(hand=('CATA_565',)); source=self.play(g,'CATA_565')
        self.assertEqual((g.state.entities[source].attack,self.board(g)[1].card_id),(1,'CATA_565t')); self.check(g)

    def test_shaman_rank_scales_printed_aura_once(self):
        for n, amount in ((0,1),(2,2),(4,4)):
            with self.subTest(n=n):
                g=self.ranked(n,hand=('plain','herald')); self.play(g,'plain'); self.play(g,'herald')
                self.assertEqual([e.attack for e in self.board(g)],[2+amount,amount]); self.check(g)

    def test_current_copy_preserves_scaled_aura(self):
        g=self.ranked(4,hand=('herald','copy'));self.play(g,'herald');self.play(g,'copy',self.board(g)[0].id)
        self.assertEqual([e.attack for e in self.board(g)],[8,8])
        self.assertEqual([next(a.attack for a in e.abilities if a.kind=='aura') for e in self.board(g)],[4,4]);self.check(g)

    def test_existing_soldier_does_not_scale_with_later_heralds(self):
        g=self.game(hand=('herald',)*3)
        for _ in range(3):self.play(g,'herald')
        self.assertEqual([next(a.attack for a in e.abilities if a.kind=='aura') for e in self.board(g)],[1,1,2]);self.check(g)

    def test_bounce_recaptures_current_rank(self):
        g=self.game(hand=('herald','herald','bounce'))
        self.play(g,'herald');old=self.board(g)[0].id;self.play(g,'herald');self.play(g,'bounce',old)
        self.play(g,'CATA_565t')
        self.assertEqual(next(a.attack for a in g.state.entities[old].abilities if a.kind=='aura'),2);self.check(g)

    def test_bounce_discards_granted_aura_before_reinstalling_printed_one(self):
        self.spell('grant_then_bounce',lambda c:[GrantAura(c.state.players[1].board[0],3,adjacent_only=True),ReturnToHand(c.state.players[1].board[0])])
        g=self.ranked(4,hand=('herald','grant_then_bounce'))
        self.play(g,'herald'); self.play(g,'grant_then_bounce'); self.play(g,'CATA_565t')
        # Bounce resets granted abilities; printed +4 is freshly installed.
        self.assertEqual([a.attack for a in self.board(g)[0].abilities if a.kind=='aura'],[4]);self.check(g)

    def test_rogue_generates_other_class_spell_at_captured_discount(self):
        for n,discount in ((0,1),(2,2),(4,4)):
            with self.subTest(n=n):
                g=self.ranked(n,hero=CardClass.ROGUE,hand=('herald',));self.play(g,'herald')
                card=g.state.entities[g.state.players[1].hand[-1]];definition=self.r.card(card.card_id)
                self.assertEqual(card.kind,CardType.SPELL);self.assertNotIn(CardClass.ROGUE,definition.metadata.classes)
                self.assertNotIn(CardClass.NEUTRAL,definition.metadata.classes)
                self.assertEqual(quote_cost(g.state,self.r,card).amount,max(0,definition.cost-discount));self.check(g)

    def test_rogue_follower_heralds_on_death_only(self):
        g=self.game(hero=CardClass.ROGUE,hand=('CATA_158','kill'));source=self.play(g,'CATA_158')
        self.assertEqual(len(g.state.herald_history),0);self.play(g,'kill',source)
        self.assertEqual(self.board(g)[0].card_id,'CATA_158t');self.assertEqual(len(g.state.players[1].hand),1);self.check(g)

    def test_generated_discount_persists_after_turn(self):
        g=self.game(hero=CardClass.ROGUE,hand=('herald',));self.play(g,'herald')
        entity=g.state.entities[g.state.players[1].hand[0]]; before=quote_cost(g.state,self.r,entity)
        g.apply(EndTurn(1));self.assertEqual(quote_cost(g.state,self.r,g.state.entities[entity.id]),before);self.check(g)

    def test_death_knight_generates_exact_printed_cost_for_each_rank(self):
        for n,cost in ((0,2),(2,4),(4,8)):
            with self.subTest(n=n):
                g=self.ranked(n,hero=CardClass.DEATH_KNIGHT,hand=('herald',));self.play(g,'herald')
                entity=g.state.entities[g.state.players[1].hand[0]]
                self.assertEqual(self.r.card(entity.card_id).cost,cost)
                self.assertEqual(quote_cost(g.state,self.r,entity).payment,PaymentType.HEALTH);self.check(g)

    def test_death_knight_battlecry_and_runes_are_adapted(self):
        g=self.game(hero=CardClass.DEATH_KNIGHT,hand=('CATA_780',));self.play(g,'CATA_780')
        self.assertEqual(self.board(g)[1].card_id,'CATA_780t')
        self.assertEqual(self.r.card('CATA_780').metadata.runes.blood,2);self.check(g)

    def test_generated_health_payment_expires_at_end_of_current_turn(self):
        g=self.game(hero=CardClass.DEATH_KNIGHT,hand=('herald',));self.play(g,'herald')
        i=g.state.players[1].hand[0];g.apply(EndTurn(1))
        self.assertEqual(quote_cost(g.state,self.r,g.state.entities[i]).payment,PaymentType.MANA);self.check(g)

    def test_generated_card_spends_health_and_not_mana(self):
        g=self.ranked(2,hero=CardClass.DEATH_KNIGHT,hand=('herald',));self.play(g,'herald')
        i=g.state.players[1].hand[0];mana=g.state.players[1].mana
        g.apply(PlayCard(1,i));hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(hero.health,26);self.assertEqual(g.state.players[1].mana,mana);self.check(g)

    def test_full_board_still_counts_without_generating_a_card(self):
        for cls in (CardClass.ROGUE,CardClass.DEATH_KNIGHT):
            g=self.game(hero=cls,board=('plain',)*7,hand=('herald',),context=None)
            self.play(g,'herald');self.assertEqual(len(g.state.players[1].hand),0)
            self.assertEqual(len(g.state.herald_history),1);self.check(g)

    def test_missing_generation_context_rolls_back_entire_herald(self):
        for cls in (CardClass.ROGUE,CardClass.DEATH_KNIGHT):
            g=self.game(hero=cls,hand=('herald',),context=None);before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,'herald')
            self.assertEqual(g.snapshot(),before)

    def test_other_summons_do_not_retrigger_existing_soldiers(self):
        g=self.game(hero=CardClass.ROGUE,hand=('herald','plain'));self.play(g,'herald')
        self.play(g,'plain');self.assertEqual(len(g.state.players[1].hand),1);self.check(g)

    def test_six_appendages_share_the_corresponding_soldier_behavior(self):
        for cid in ('CATA_153t','CATA_153t1','CATA_154t','CATA_154t1','CATA_155t','CATA_155t1'):
            self.spell('summon_'+cid,lambda c,cid=cid:[Summon(c.player_id,cid)])
        for cid,cls in (('CATA_153t',CardClass.SHAMAN),('CATA_153t1',CardClass.SHAMAN),
                        ('CATA_154t',CardClass.ROGUE),('CATA_154t1',CardClass.ROGUE),
                        ('CATA_155t',CardClass.DEATH_KNIGHT),('CATA_155t1',CardClass.DEATH_KNIGHT)):
            with self.subTest(cid=cid):
                g=self.ranked(4,hero=cls,hand=('summon_'+cid,));self.play(g,'summon_'+cid)
                self.assertEqual(self.board(g)[0].herald_rank,2)
                self.assertEqual(len(g.state.players[1].hand),0 if cls==CardClass.SHAMAN else 1);self.check(g)

    def test_explicit_herald_pool_is_not_inferred_from_registry(self):
        self.assertEqual({m.card_id for m in self.r.pool(HERALD_POOL_ID, CONTEXT).members},set(HERALD_POOL_IDS))
        self.assertNotIn('plain',self.r.pool_cards)

    def test_cost_is_installed_before_creation_trigger(self):
        self.r.register_behavior('watch',lambda c:[GainArmor(1,local_cost(c.state.entities[c.event.target_id])[0])])
        self.r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=1,triggers=(TriggerSpec('card_created','watch'),)))
        self.spell('generate',lambda c:[AddToHand(1,'CS2_182',cost=CostSpec(set_to=1))])
        g=self.game(board=('watch',),hand=('generate',));self.play(g,'generate')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.check(g)

    def test_generated_cost_is_visible_only_to_owning_player(self):
        g=self.game(hero=CardClass.DEATH_KNIGHT,hand=('herald',));self.play(g,'herald')
        own=g.observe(1)['players'][0]['hand'][0];hidden=g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(own['cost'],{'amount':2,'payment':'health'})
        self.assertEqual(set(hidden),{'ref','card_id'});self.assertIsNone(hidden['card_id']);self.check(g)

    def test_second_generated_card_burns_with_its_cost_already_installed(self):
        self.spell('generate',lambda c:[AddToHand(1,'CS2_182',cost=CostSpec(set_to=1)),
            AddToHand(1,'CS2_179',cost=CostSpec(payment=PaymentType.HEALTH),expires_turn=c.state.turn)])
        g=self.game(hand=('generate',*('plain',)*9));self.play(g,'generate')
        burned=next(e for e in g.state.entities.values() if e.card_id=='CS2_179')
        self.assertEqual(burned.zone,Zone.GRAVEYARD);self.assertEqual(local_cost(burned),(4,PaymentType.HEALTH));self.check(g)

    def test_current_copy_keeps_generated_discount_and_expiry(self):
        self.spell('generate',lambda c:[AddToHand(1,'CS2_182',cost=CostSpec(delta=-2,payment=PaymentType.HEALTH),expires_turn=c.state.turn)])
        self.spell('duplicate',lambda c:[CopyCard(CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand
            if c.state.entities[i].card_id=='CS2_182')),1,Zone.HAND)])
        g=self.game(hand=('generate','duplicate'));self.play(g,'generate');self.play(g,'duplicate')
        copies=[g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([local_cost(e) for e in copies],[(2,PaymentType.HEALTH)]*2)
        g.apply(EndTurn(1));self.assertEqual([local_cost(g.state.entities[e.id]) for e in copies],[(4,PaymentType.MANA)]*2);self.check(g)

    def test_generated_cost_composes_with_live_cost_aura(self):
        from hs_sim.engine.effects import GrantCostAura
        self.spell('generate',lambda c:[GrantCostAura(c.state.players[1].board[0],CostAuraSpec(CostSpec(delta=2))),
            AddToHand(1,'CS2_182',cost=CostSpec(set_to=1))])
        g=self.game(hand=('generate',),board=('plain',));self.play(g,'generate')
        e=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual(local_cost(e)[0],1);self.assertEqual(quote_cost(g.state,self.r,e).amount,3);self.check(g)

    def test_generated_deck_cost_survives_drawing(self):
        from hs_sim.engine.effects import Draw
        self.spell('generate',lambda c:[AddToDeck(1,'CS2_182','top',cost=CostSpec(set_to=1)),Draw(1)])
        g=self.game(hand=('generate',));self.play(g,'generate')
        self.assertEqual(local_cost(g.state.entities[g.state.players[1].hand[0]]),(1,PaymentType.MANA));self.check(g)

    def test_generated_deck_temporary_payment_expires_before_draw(self):
        self.spell('generate',lambda c:[AddToDeck(1,'CS2_182','top',cost=CostSpec(payment=PaymentType.HEALTH),expires_turn=c.state.turn)])
        g=self.game(hand=('generate',));self.play(g,'generate');i=g.state.players[1].deck[0]
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertIn(i,g.state.players[1].hand);self.assertEqual(local_cost(g.state.entities[i]),(4,PaymentType.MANA));self.check(g)

    def test_generation_cost_and_expiry_survive_pending_choice(self):
        self.spell('choose',lambda c:[RequestChoice(1,(ChoiceOption('a','A',(
            GenerateFromPool(1,HERALD_POOL_ID,PoolQuery(kinds=(CardType.MINION,),min_cost=4,max_cost=4),
                destination='deck',position='top',cost=CostSpec(set_to=1,payment=PaymentType.HEALTH),expires_turn=c.state.turn),)),))])
        g=self.game(hand=('choose',));self.play(g,'choose');self.check(g)
        restored=g.clone()
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('a',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(local_cost(g.state.entities[g.state.players[1].deck[0]]),(1,PaymentType.HEALTH));self.check(g)

    def test_expired_generation_is_transactional(self):
        factories = (lambda:AddToHand(1,'CS2_182',cost=CostSpec(delta=-1),expires_turn=1),
                        lambda:AddToDeck(1,'CS2_182',cost=CostSpec(delta=-1),expires_turn=1),
                        lambda:GenerateFromPool(1,HERALD_POOL_ID,cost=CostSpec(delta=-1),expires_turn=1))
        for i,factory in enumerate(factories):self.spell(f'expired{i}',lambda c,factory=factory:[factory()])
        for i in range(len(factories)):
            g=self.game(hand=(f'expired{i}',))
            g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'expired'):self.play(g,f'expired{i}')
            self.assertEqual(g.snapshot(),before)

    def test_cost_type_mismatch_checks_all_eligible_candidates(self):
        self.spell('wrong',lambda c:[GenerateFromPool(1,HERALD_POOL_ID,
            cost=CostSpec(card_types=(CardType.SPELL,),delta=-1))])
        g=self.game(hand=('wrong',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'card type'):self.play(g,'wrong')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_generated_cost_descriptors_rejected(self):
        factories=(lambda **kw:AddToHand(1,'CS2_182',**kw),lambda **kw:AddToDeck(1,'CS2_182',**kw),
                   lambda **kw:GenerateFromPool(1,HERALD_POOL_ID,**kw))
        for f in factories:
            for kw in ({'expires_turn':1},{'cost':'health'},{'cost':CostSpec(),'expires_turn':True},{'cost':CostSpec(),'expires_turn':0}):
                with self.assertRaises(ValueError):f(**kw)
        with self.assertRaises(ValueError):GenerateFromPool(1,HERALD_POOL_ID,destination='board',cost=CostSpec(delta=-1))

    def test_snapshot_rejects_non_boolean_adjacent_flag(self):
        g=self.game(board=('aura',));data=g.snapshot()
        for entity in data['state']['entities'].values():
            for a in entity['abilities']:
                if a['kind']=='aura':a['adjacent_only']=1
        data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_schema_34_rejected(self):
        data=self.game().snapshot();data['schema_version']=34
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)


if __name__ == '__main__':
    unittest.main()
