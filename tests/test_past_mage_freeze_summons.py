"""Real past Mage effects through paid entry, original references and recovery."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import past_mage_freeze_summons as native
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SnapshotError, TriggerSpec, UseHandAction)
from hs_sim.engine.captured_minion_spell_groups import DamageCapturedMinionGroup
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Freeze, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.model import DamageKind, TargetSpec, Zone
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

POTION, CONE, METEOR, SOUL, BREATH, SALE, EXILE, SNAP, RAY, MIRROR, DEEP, GEYSER, FIRST, RIPPLE, BRAIN = native.LEAVES
TWIN, IMAGE = native.TOKENS
WATER, ELEMENTAL, SECOND = native.EXISTING
P = 'k602.'
UNIT, LEFT, RIGHT, SMALL, POWER, DORMANT, LOCATION, NOOP, WAIT, RANDOM_WAIT, FILL, FAIL, AUTO = (
    P+x for x in ('unit','left','right','small','power','dormant','location','noop','wait','random_wait','fill','fail','auto'))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r = build_registry()
    def fail(c):raise ResolutionError('K602 deliberate continuation failure')
    r.register_behavior(FAIL,fail)
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,BRAIN,c.source_id,targeting='explicit',target_id=c.target_id),))
    for cid,body,targets in ((NOOP,NOOP,None),(AUTO,AUTO,TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=body,targeting=targets))
    for cid,health,power,dormant in ((UNIT,20,0,0),(LEFT,20,0,0),(RIGHT,20,0,0),(SMALL,1,0,0),(POWER,2,2,0),(DORMANT,20,0,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=health,spell_damage=power,dormant_turns=dormant))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=NOOP))
    def watch(c):
        event = c.event;source = c.state.entities.get(event.source_id)
        if source is None:return ()
        if c.source.card_id == WAIT and event.kind == 'frozen' and source.card_id in (CONE,SOUL,BRAIN):
            target = c.state.entities[event.target_id]
            if target.card_id != LEFT:return ()
            options = (ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),)),
                ChoiceOption('replace','Replace original left',(Destroy(target.id,c.source_id),Summon(target.controller,LEFT,position=0))))
            return (RequestChoice(c.player_id,options,c.source_id),)
        if c.source.card_id == RANDOM_WAIT and event.kind == 'random_choice' and source.card_id == BREATH:
            target = c.state.entities[int(dict(event.data)['selected'])]
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('remove','Remove selected',(Destroy(target.id,c.source_id),))),c.source_id),)
        if c.source.card_id == FILL and event.kind == 'damage_dealt' and source.card_id in (GEYSER,FIRST):
            return (AddToHand(c.player_id,NOOP,c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    for cid in (WAIT,RANDOM_WAIT,FILL):r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,
        triggers=tuple(TriggerSpec(event,P+'watch')for event in ('frozen','random_choice','damage_dealt'))))
    r.validate();return r


class PastMageFreezeSummonTests(CardBatchTestMixin,unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(registry)

    def game(self,hand=(),*,deck=(NOOP,)*4,board=(),enemy_board=(),player=1):
        setups=tuple(PlayerSetup('HERO_08',hand=hand if p == player else (),deck=deck,
            board=board if p == player else enemy_board,mana=30,max_mana=30,mana_cap=30)for p in (1,2))
        return Game.from_scenario(Scenario(setups,active_player=player,seed=602),registry())

    def paid(self,g,cid,target=None,player=1):
        mana=g.state.players[player].mana;source=self.play(g,cid,target,player)
        self.assertEqual(g.state.players[player].mana,mana-g.registry.card(cid).cost)
        self.assertEqual((g.state.play_history[-1].card_id,g.state.play_history[-1].cost),(cid,g.registry.card(cid).cost));return source

    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]

    def test_twenty_full_sources_forty_primary_faces_original_tokens_and_printed_zeros(self):
        data=native.load_batch();rows={r['record']['id']:r for r in (*data['dependencies'],*data['existing_dependencies'])}
        self.assertEqual((len(rows),len(data['official_observations'])),(20,40))
        for obs in data['official_observations']:
            batch.check_face(rows[obs['card_id']]['record'],obs['face'],obs['locale'],numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
        r=registry();self.assertEqual((r.card(POTION).cost,r.card(IMAGE).cost,r.card(IMAGE).attack,r.card(IMAGE).health),(0,0,0,2))
        self.assertIn(Keyword.TAUNT,r.card(IMAGE).keywords);self.assertNotIn(Keyword.TWINSPELL,r.card(TWIN).keywords)
        for row in data['existing_dependencies']:
            self.assertEqual(batch.canonical(__import__('dataclasses').asdict(r.card(row['record']['id']))),row['definition_sha256'])
        self.assertEqual(native.COLLECTIBLE_ROOTS,())

    def test_zero_cost_potion_accepts_only_enemy_characters_in_both_seats(self):
        for player in (1,2):
            g=self.game((POTION,),board=(UNIT,),enemy_board=(UNIT,),player=player);before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,POTION,g.state.players[player].hero_id,player)
            self.assertEqual(g.snapshot(),before);self.paid(g,POTION,g.state.players[3-player].hero_id,player)
            self.assertTrue(self.hero(g,3-player).frozen)
        self.portable(g)

    def test_cone_original_three_targets_share_one_damage_batch_bonus(self):
        g=self.game((CONE,),board=(POWER,),enemy_board=(LEFT,UNIT,RIGHT));targets=tuple(g.state.players[2].board)
        self.paid(g,CONE,targets[1]);self.assertEqual([g.state.entities[i].health for i in targets],[17]*3)
        self.assertTrue(all(g.state.entities[i].frozen for i in targets));self.portable(g)

    def test_cone_bonus_is_shared_before_its_own_frozen_provider_dies(self):
        g=self.game((CONE,),board=(LEFT,POWER,RIGHT));targets=tuple(g.state.players[1].board)
        self.paid(g,CONE,targets[1]);self.assertNotIn(targets[1],g.state.players[1].board)
        self.assertEqual([g.state.entities[i].health for i in (targets[0],targets[2])],[17,17]);self.portable(g)

    def test_immediate_location_or_dormant_gap_never_promotes_farther_neighbor(self):
        for gap in (LOCATION,DORMANT):
            for cid in (CONE,METEOR):
                g=self.game((cid,),enemy_board=(LEFT,gap,UNIT,RIGHT));targets=tuple(g.state.players[2].board)
                self.paid(g,cid,targets[2]);self.assertEqual(g.state.entities[targets[0]].health,20)
                self.assertFalse(g.state.entities[targets[0]].frozen)
                self.assertEqual(g.state.entities[targets[3]].health,19 if cid == CONE else 16)
        self.portable(g)

    def test_meteor_preserves_fifteen_four_four_amounts_and_minion_only_target(self):
        for player in (1,2):
            g=self.game((METEOR,),board=(POWER,),enemy_board=(LEFT,UNIT,RIGHT),player=player);targets=tuple(g.state.players[3-player].board);before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,METEOR,g.state.players[3-player].hero_id,player)
            self.assertEqual(g.snapshot(),before);self.paid(g,METEOR,targets[1],player)
            self.assertEqual([g.state.entities[i].health for i in targets],[14,3,14]);self.assertFalse(any(g.state.entities[i].frozen for i in targets))
        self.portable(g)

    def test_waiting_cone_restores_original_group_and_ignores_replacement_neighbor(self):
        g=self.game((CONE,),board=(WAIT,),enemy_board=(LEFT,UNIT,RIGHT));targets=tuple(g.state.players[2].board)
        self.paid(g,CONE,targets[1]);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);before=other.snapshot()
        with self.assertRaises(ResolutionError):self.choose(other,'fault')
        self.assertEqual(other.snapshot(),before);self.choose(other,'replace')
        replacement=other.state.players[2].board[0];self.assertNotEqual(replacement,targets[0])
        self.assertEqual(other.state.entities[replacement].health,20);self.assertFalse(other.state.entities[replacement].frozen)
        self.assertEqual([other.state.entities[i].health for i in targets[1:]],[19,19]);self.portable(other)

    def test_soulfreeze_uses_original_neighbor_count_then_shared_self_spell_damage(self):
        for player in (1,2):
            g=self.game((SOUL,),enemy_board=(LEFT,UNIT,RIGHT),player=player);targets=tuple(g.state.players[3-player].board)
            self.paid(g,SOUL,targets[1],player);self.assertEqual(self.hero(g,player).health,27)
            self.assertTrue(all(g.state.entities[i].frozen for i in targets));self.assertTrue(all(g.state.entities[i].health == 20 for i in targets))
        self.portable(g)

    def test_soulfreeze_wait_does_not_recount_after_original_target_group_changes(self):
        g=self.game((SOUL,),board=(WAIT,),enemy_board=(LEFT,UNIT,RIGHT));target=g.state.players[2].board[1]
        self.paid(g,SOUL,target);other=self.portable(g);self.choose(other,'replace')
        self.assertEqual(self.hero(other,1).health,27);self.portable(other)

    def test_breath_minimum_gate_random_enemy_only_and_damage_precedes_freeze(self):
        g=self.game((BREATH,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BREATH)
        self.assertEqual(g.snapshot(),before)
        g=self.game((BREATH,),board=(POWER,),enemy_board=(LEFT,RIGHT));targets=tuple(g.state.players[2].board);source=self.paid(g,BREATH)
        hit=[i for i in targets if g.state.entities[i].health == 16];self.assertEqual(len(hit),1)
        self.assertTrue(g.state.entities[hit[0]].frozen);self.assertFalse(g.state.entities[next(i for i in targets if i not in hit)].frozen)
        kinds=[e.kind for e in g.events if e.source_id == source];self.assertLess(kinds.index('damage_dealt'),kinds.index('frozen'));self.portable(g)

    def test_breath_selected_death_does_not_freeze_a_dead_entity_or_reselect(self):
        g=self.game((BREATH,),enemy_board=(SMALL,));target=g.state.players[2].board[0]
        self.paid(g,BREATH);self.assertNotIn(target,g.state.players[2].board)
        self.assertFalse(any(e.kind == 'frozen'and e.target_id == target for e in g.events));self.portable(g)

    def test_random_choice_wait_retains_selected_reference_when_removed(self):
        g=self.game((BREATH,),board=(RANDOM_WAIT,),enemy_board=(LEFT,RIGHT));self.paid(g,BREATH)
        other=self.portable(g);self.choose(other,'remove')
        self.assertFalse(other.state.damage_history);self.assertEqual(len(other.state.players[2].board),1)
        survivor=other.state.entities[other.state.players[2].board[0]];self.assertEqual(survivor.health,20);self.assertFalse(survivor.frozen);self.portable(other)

    def test_snap_freeze_destroys_only_initially_frozen_target(self):
        g=self.game((SNAP,SNAP),enemy_board=(UNIT,));target=g.state.players[2].board[0]
        self.paid(g,SNAP,target);self.assertIn(target,g.state.players[2].board);self.assertTrue(g.state.entities[target].frozen)
        self.paid(g,SNAP,target);self.assertNotIn(target,g.state.players[2].board);self.assertFalse(g.state.damage_history);self.portable(g)

    def test_real_twinspell_delivers_original_terminal_face_and_second_cast_deals_damage(self):
        g=self.game((RAY,),board=(POWER,),enemy_board=(UNIT,));target=g.state.players[2].board[0];source=self.paid(g,RAY,target)
        twin=self.entity(g,TWIN);self.assertNotEqual(twin.id,source);self.assertTrue(g.state.entities[target].frozen)
        self.paid(g,TWIN,target);self.assertEqual(g.state.entities[target].health,16)
        self.assertFalse(any(g.state.entities[i].card_id in (RAY,TWIN)for i in g.state.players[1].hand));self.portable(g)

    def test_mirror_image_summons_two_real_zero_attack_taunts_with_original_attribution(self):
        for player in (1,2):
            g=self.game((MIRROR,),player=player);self.paid(g,MIRROR,player=player)
            copies=[g.state.entities[i]for i in g.state.players[player].board]
            self.assertEqual([x.card_id for x in copies],[IMAGE,IMAGE]);self.assertEqual([(x.attack,x.health)for x in copies],[(0,2),(0,2)])
            self.assertTrue(all(Keyword.TAUNT in x.keywords for x in copies));self.assertNotEqual(copies[0].id,copies[1].id)
            self.assertTrue(g.state.card_summon_history)
        self.portable(g)

    def test_named_two_summon_batches_respect_remaining_capacity(self):
        for cid,body in ((MIRROR,IMAGE),(DEEP,WATER)):
            g=self.game((cid,),board=(UNIT,)*6);target=g.state.players[2].hero_id if cid == DEEP else None
            self.paid(g,cid,target);self.assertEqual(len(g.state.players[1].board),7)
            self.assertEqual(g.state.entities[g.state.players[1].board[-1]].card_id,body)
        self.portable(g)

    def test_deep_freeze_enemy_hero_and_real_water_elementals_keep_damage_freeze_behavior(self):
        g=self.game((DEEP,));self.paid(g,DEEP,g.state.players[2].hero_id)
        waters=tuple(g.state.players[1].board);self.assertEqual([g.state.entities[i].card_id for i in waters],[WATER,WATER])
        self.assertTrue(self.hero(g,2).frozen);g.apply(EndTurn(1));g.apply(EndTurn(2))
        g.apply(Attack(1,waters[0],g.state.players[2].hero_id));self.assertTrue(self.hero(g,2).frozen);self.portable(g)

    def test_geyser_and_first_flame_deliver_original_real_hand_dependencies(self):
        for player in (1,2):
            g=self.game((GEYSER,FIRST),enemy_board=(UNIT,),player=player);target=g.state.players[3-player].board[0]
            self.paid(g,GEYSER,target,player);element=self.entity(g,ELEMENTAL,player);self.assertEqual((element.attack,element.health),(1,2))
            self.paid(g,FIRST,target,player);self.paid(g,SECOND,target,player)
            self.assertEqual(g.state.entities[target].health,14)
        self.portable(g)

    def test_damage_reaction_full_hand_uses_normal_token_burn(self):
        for cid,body in ((GEYSER,ELEMENTAL),(FIRST,SECOND)):
            g=self.game((cid,)+(NOOP,)*9,board=(FILL,),enemy_board=(UNIT,));self.paid(g,cid,g.state.players[2].board[0])
            self.assertEqual(len(g.state.players[1].hand),10)
            self.assertFalse(any(g.state.entities[i].card_id == body for i in g.state.players[1].hand))
            self.assertTrue(any(g.state.entities[i].card_id == body for i in g.state.players[1].graveyard))
        self.portable(g)

    def test_life_sentence_removes_original_minion_without_death_or_deathrattle(self):
        g=self.game((EXILE,),enemy_board=(WATER,));target=g.state.players[2].board[0];self.paid(g,EXILE,target)
        self.assertNotIn(target,g.state.players[2].board);self.assertNotIn(target,g.state.players[2].graveyard)
        self.assertFalse(g.state.death_history);self.assertTrue(any(e.kind == 'cards_removed_from_game'for e in g.events));self.portable(g)

    def test_ripple_gives_friendly_local_spell_damage_or_freezes_enemy(self):
        g=self.game((RIPPLE,RIPPLE,GEYSER),board=(UNIT,),enemy_board=(UNIT,));own=g.state.players[1].board[0];enemy=g.state.players[2].board[0]
        self.paid(g,RIPPLE,own);self.assertFalse(g.state.entities[own].frozen)
        self.paid(g,RIPPLE,enemy);self.assertTrue(g.state.entities[enemy].frozen)
        self.paid(g,GEYSER,enemy);self.assertEqual(g.state.entities[enemy].health,17);self.portable(g)

    def test_brain_freeze_uses_original_paid_combo_condition_and_automatic_cast_policy(self):
        g=self.game((BRAIN,BRAIN,AUTO),enemy_board=(UNIT,));target=g.state.players[2].board[0]
        self.paid(g,BRAIN,target);self.assertEqual(g.state.entities[target].health,20)
        self.paid(g,BRAIN,target);self.assertEqual(g.state.entities[target].health,17)
        self.assertTrue(g.state.cast_history[-1].combo);self.play(g,AUTO,target)
        self.assertEqual(g.state.entities[target].health,14);self.assertTrue(g.state.cast_history[-1].combo);self.portable(g)

    def test_brain_freeze_wait_keeps_original_reference_for_combo_damage(self):
        g=self.game((NOOP,BRAIN),board=(WAIT,),enemy_board=(LEFT,));self.play(g,NOOP);target=g.state.players[2].board[0]
        self.paid(g,BRAIN,target);other=self.portable(g);self.choose(other,'replace')
        replacement=other.state.players[2].board[0];self.assertNotEqual(replacement,target)
        self.assertEqual(other.state.entities[replacement].health,20);self.portable(other)

    def test_fire_sale_damage_and_true_tradeable_action_are_independent(self):
        g=self.game((SALE,),board=(POWER,),enemy_board=(UNIT,));enemy=g.state.players[2].board[0]
        self.paid(g,SALE);self.assertEqual(g.state.entities[enemy].health,15);self.assertEqual(g.state.players[1].board,[])
        g=self.game((SALE,),deck=(NOOP,));source=self.entity(g,SALE).id
        self.assertTrue(any(isinstance(a,UseHandAction)and a.action_id == 'trade'for a in g.legal_actions()))
        g.apply(UseHandAction(1,source,'trade'));self.assertEqual(g.state.players[1].mana,29)
        self.assertFalse(g.state.cast_history);self.assertFalse(g.state.damage_history);self.portable(g)

    def test_captured_group_typed_shape_allocations_and_missing_source_are_checked(self):
        g=self.game((CONE,),enemy_board=(LEFT,UNIT));source=self.entity(g,CONE).id;refs=tuple(MinionReference.capture(g.state.entities[i])for i in g.state.players[2].board)
        request=DamageCapturedMinionGroup(refs,(1,1),source);request.validate_in_state(g.state,g.registry)
        for build in (lambda:replace(request,amounts=(1,)),lambda:replace(request,targets=(refs[0],refs[0])),lambda:replace(request,amounts=(True,1)),
                lambda:replace(request,targets=(replace(refs[0],entered_order=g.state.next_order),refs[1])),lambda:replace(request,source_id=g.state.players[1].hero_id)):
            with self.assertRaises(ValueError):build().validate_in_state(g.state,g.registry)

    def test_waiting_group_is_private_and_old_schema_is_explicitly_rejected(self):
        g=self.game((CONE,),board=(WAIT,),enemy_board=(LEFT,UNIT,RIGHT));self.paid(g,CONE,g.state.players[2].board[1]);saved=g.snapshot()
        for player in (1,2):
            text=json.dumps(g.for_player(player).observe())
            for field in ('rng_state','resolution_frame','entered_order','zone_epoch','amounts'):self.assertNotIn('"'+field+'"',text)
        saved['schema_version']=607
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry('normal','independent-reader'))

    def test_last_bad_dependency_does_not_leave_partial_registration(self):
        original=native.register_past_mage_freeze_summons
        prefix=batch.registration_prefix(build_registry,'hs_sim.cards.past_mage_freeze_summons.register_past_mage_freeze_summons',original)
        data=deepcopy(native.load_batch());data['dependencies'][-1]['record']['type']='SPELL';before=prefix.fingerprint()
        with patch.object(native,'load_batch',return_value=data),self.assertRaises(ValueError):original(prefix)
        self.assertEqual(prefix.fingerprint(),before)
