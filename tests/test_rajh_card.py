"""Real Rajh entry and passive installation in explicit reviewed fixture domains."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.rajh_card import CARD, POWER, POOL, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleRecipe, AssembleSuffix, AssembleTemplate, recipe_from_id
from hs_sim.engine.assemble_offers import Assemble, ResolveAssemble, validate_offer
from hs_sim.engine.assembled_powers import (AssembledPowerRecipe, AssembledPowerProfile,
    power_recipe_from_id)
from hs_sim.engine.battlecry_sources import RepeatBattlecry
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, InvokeBehavior,
    ReplaceHeroPower, RequestChoice)
from hs_sim.engine.model import CardClass, CardMetadata, ChoicePurpose, CostSpec, EndTurnSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

DANCER, ASCENDANT, YESTERLOC = 'BE_152', 'CORE_ICC_210', 'TIME_428'
MEMBERS = (DANCER, ASCENDANT, YESTERLOC)
P = 'fixture.rajh.'
ZERO, UNIT, RESET, HOST, WATCH, FAIL, BAD = (P+x for x in ('zero','unit','reset','host','watch','fail','unknown'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CTX = GenerationContext('k390-explicit-reviewed-passive-fixture', 'experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    registry = build_registry()
    registry._version += '.fixture.rajh.'+mode
    registry.register_behavior(ZERO, lambda c: ())
    registry.register_card(CardDefinition(ZERO, 'Explicit empty starter', CardType.SPELL, on_play=ZERO, metadata=META))
    registry.register_card(CardDefinition(UNIT, 'Explicit friendly subject', CardType.MINION, attack=1, health=20, metadata=META))
    registry.register_behavior(RESET, lambda c: (ReplaceHeroPower(c.player_id, 'HERO_04bp', source_id=c.source_id),))
    registry.register_card(CardDefinition(RESET, 'Explicit power replacement', CardType.SPELL, on_play=RESET, metadata=META))
    def historical(c):
        old = next(x for x in c.state.battlecry_history if x.payload.card_id == CARD and x.completed)
        return (RepeatBattlecry(c.player_id, c.source_id, old.id, choices='player'),)
    registry.register_behavior(HOST, historical)
    registry.register_card(CardDefinition(HOST, 'Explicit history carrier', CardType.MINION,
        attack=1, health=5, battlecry=HOST, metadata=META))
    members = MEMBERS
    if mode == 'unknown':
        registry.register_pool_card(PoolCard(BAD, CardType.MINION, 2, META)); members += (BAD,)
    if mode == 'incompatible': members += ('CORE_EX1_096',)
    if mode == 'general-only':
        card = CardDefinition(BAD, 'Explicit unreviewed power-context counterexample', CardType.MINION,
            cost=2, attack=1, health=1, metadata=META, triggers=(TriggerSpec('turn_ended',ZERO,EndTurnSpec()),))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
        registry.register_assemble_template(AssembleTemplate(BAD,AssemblePrefix('end_turn',end_turn=EndTurnSpec()),
            AssembleSuffix(ZERO,('end_turn',))))
        members += (BAD,)
    if mode != 'missing':
        registry.register_pool(PoolDefinition(POOL, 'fixture-'+mode, CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    def fail(c): raise ResolutionError('Intentional installed-power reaction failure')
    registry.register_behavior(FAIL, fail)
    def watch(c):
        target = c.state.entities.get(c.event.target_id)
        if mode == 'fill':
            source = c.state.entities.get(c.event.source_id)
            return (AddToHand(c.player_id, ZERO, c.source_id),) if source is not None and source.card_id == CARD else ()
        if target is None or not target.card_id.startswith('assemble-power:'): return ()
        if mode == 'fail': return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'retire':
            root = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == CARD)
            return (Destroy(root, c.source_id),)
        if mode == 'wait': return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue original power installation'),
            ChoiceOption('fail', 'Rollback this nested choice', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()
    registry.register_behavior(WATCH, watch)
    registry.register_card(CardDefinition(WATCH, 'Explicit original-window observer', CardType.MINION,
        attack=1, health=20, metadata=META,
        triggers=(TriggerSpec('card_committed' if mode == 'fill' else 'hero_power_replaced', WATCH),)))
    return registry


class RajhTests(unittest.TestCase):
    readers = {}

    def game(self, hand=(CARD,), mode='normal', hero='HERO_04', board=(UNIT, UNIT)):
        own = (*board, WATCH) if mode in ('fill','fail','retire','wait') else board
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hero_power_card_id=hero+'bp', hand=hand, board=own,
                deck=(ZERO,)*12, mana=10, max_mana=10),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=(ZERO,),
                deck=(ZERO,)*12, mana=10, max_mana=10)), seed=0, generation_context=CTX), fixture(mode))

    def play(self, game, cid):
        eid = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == cid)
        from hs_sim.engine import PlayCard
        game.apply(PlayCard(1, eid)); return eid

    def offer(self, game):
        return next(e.offer for o in game._frame.options for e in o.effects if isinstance(e, ResolveAssemble))

    def choose(self, game, option=None):
        choice = game.state.pending_choice; option = option or choice.options[0]
        game.apply(SelectChoice(1, choice.id, (option.id,))); return option.card_id

    def power(self, game): return game.state.entities[game.state.players[1].hero_power_id]

    def portable(self, game, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        registry = self.readers[mode]; saved = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        return Game.from_snapshot(saved, registry)

    def test_five_complete_records_ten_full_faces_and_real_dynamic_zero_cost_template(self):
        data = load_batch(); records = {x['record']['id']: x['record'] for key in
            ('cards','dependencies','existing_dependencies') for x in data[key]}
        self.assertEqual(len(records), 5); self.assertEqual(len(data['official_observations']), 10)
        for item in data['official_observations']:
            dynamic = item['card_id'] == POWER
            check_face(records[item['card_id']], item['face'], item['locale'],
                {'{0}':''} if dynamic else None, numeric_normalizations={'cost':0} if dynamic else None)
        self.assertIsNone(records[POWER]['cost']); self.assertEqual(records[POWER]['text'], '{0}')
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertFalse(data['policy']['secondary_cost_rule_confirmed'])
        self.assertEqual((fixture().card(CARD).cost, fixture().card(CARD).attack, fixture().card(CARD).health), (5,4,4))

    def test_template_display_exception_rejects_other_parent_numeric_and_source_text(self):
        data = load_batch(); raw = data['dependencies'][0]['record']
        item = next(x for x in data['official_observations'] if x['card_id'] == POWER)
        for changed in ({**item['face'],'parentId':1}, {**item['face'],'manaCost':1}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                check_face(raw, changed, item['locale'], {'{0}':''}, numeric_normalizations={'cost':0})
        other = deepcopy(raw); other['text'] += '禁止忽略真实规则'
        with self.assertRaises(ValueError):
            check_face(other, item['face'], item['locale'], {'{0}':''}, numeric_normalizations={'cost':0})

    def test_actual_paid_battlecry_accepts_full_separate_multiclass_and_neutral_domain(self):
        game = self.game(); old = self.power(game).id; source = self.play(game, CARD); offer = self.offer(game)
        self.assertEqual(game.state.players[1].mana, 5); self.assertEqual(self.power(game).id, old)
        self.assertEqual(offer.spec.source_id, source); self.assertEqual(offer.spec.passive_power_template_id, POWER)
        self.assertEqual(set(offer.primary_candidates), set(MEMBERS))
        self.assertEqual(set(offer.secondary_candidates), set(MEMBERS)-{offer.primary_card_id})
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.ASSEMBLE)
        self.assertTrue(all(game.registry.card(x.card_id).kind == CardType.HERO_POWER for x in game.state.pending_choice.options))

    def test_current_mage_does_not_narrow_either_curated_pool_to_mage(self):
        game = self.game(hero='HERO_08'); self.play(game, CARD); offer = self.offer(game)
        self.assertEqual(set(offer.primary_candidates), set(MEMBERS))
        self.assertEqual(set(offer.secondary_candidates), set(MEMBERS)-{offer.primary_card_id})
        self.assertEqual(offer.before.players[1].hero_class, CardClass.MAGE)

    def test_real_selection_installs_one_new_passive_and_never_creates_an_intermediate_hand_minion(self):
        game = self.game(); old = self.power(game).id; self.play(game, CARD); rng = game.snapshot()['rng_state']
        cid = self.choose(game); power = self.power(game); definition = game.registry.card(cid)
        self.assertEqual(power.card_id, cid); self.assertNotEqual(power.id, old)
        self.assertEqual(game.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual((definition.kind, definition.cost, definition.passive_hero_power), (CardType.HERO_POWER,0,True))
        self.assertEqual(definition.name, '阳炎耀光'); self.assertEqual(game.state.players[1].hand, [])
        self.assertEqual(game.state.players[1].mana, 5); self.assertEqual(game.snapshot()['rng_state'], rng)
        self.assertFalse(any(e.card_id.startswith('assemble:') for e in game.state.entities.values()))
        self.assertEqual(game.state.hero_power_history, [])

    def test_every_actual_selected_suffix_executes_as_a_native_power_at_owner_end(self):
        game = self.game(); self.play(game, CARD); saved = self.portable(game).snapshot()
        for option in game.state.pending_choice.options:
            with self.subTest(option=option.id):
                value = Game.from_snapshot(saved, self.readers['normal']); self.choose(value, option)
                recipe = recipe_from_id(power_recipe_from_id(option.card_id).minion_card_id)
                donor = recipe.secondary_card_id
                before = {i:(value.state.entities[i].attack,value.state.entities[i].health)
                    for i in value.state.players[1].board}
                value.apply(EndTurn(1))
                after = {i:(value.state.entities[i].attack,value.state.entities[i].health) for i in before}
                if donor == DANCER:
                    self.assertEqual([value.state.entities[i].card_id for i in value.state.players[1].hand], ['BE_152t'])
                    self.assertEqual(after, before)
                elif donor == ASCENDANT:
                    changed = [i for i in before if after[i] != before[i]]; self.assertEqual(len(changed), 1)
                    i, = changed; self.assertEqual(after[i], (before[i][0]+1,before[i][1]+1))
                elif donor == YESTERLOC:
                    self.assertEqual(after, {i:(a,h+1) for i,(a,h) in before.items()})
                else: self.fail('Unexpected unreviewed suffix')
                self.assertEqual(value.state.hero_power_history, [])
                self.assertEqual(value.state.players[1].mana, 5)

    def test_full_hand_does_not_burn_or_block_the_direct_power_installation(self):
        game = self.game(hand=(CARD,)+(ZERO,)*9, mode='fill'); self.play(game, CARD)
        self.assertEqual(len(game.state.players[1].hand), 10); self.choose(game)
        self.assertEqual(len(game.state.players[1].hand), 10)
        self.assertTrue(self.power(game).card_id.startswith('assemble-power:'))
        self.assertFalse(any(e.card_id.startswith('assemble:') for e in game.state.entities.values()))

    def test_passive_power_never_has_a_manual_legal_use_or_use_history(self):
        game = self.game(); self.play(game, CARD); self.choose(game); saved = game.snapshot()
        with self.assertRaises(IllegalAction): game.apply(UseHeroPower(1,self.power(game).id))
        self.assertEqual(game.snapshot(), saved)
        actions = game.for_player(1).legal_actions()['actions']
        self.assertFalse(any(a['type'] == 'use_hero_power' for a in actions))
        self.assertEqual(game.state.hero_power_history, [])

    def test_pending_and_completed_installation_restore_clone_and_replay_without_resampling(self):
        game = self.game(); self.play(game, CARD); other = self.portable(game)
        self.choose(game); self.choose(other); self.assertEqual(game.snapshot(), other.snapshot())
        self.portable(game); game.apply(EndTurn(1)); self.portable(game)

    def test_accepted_power_survives_real_root_death_after_installation(self):
        game = self.game(mode='retire'); root = self.play(game, CARD); self.choose(game)
        self.assertEqual(game.state.entities[root].zone, Zone.GRAVEYARD)
        self.assertEqual(self.power(game).zone, Zone.HERO_POWER)
        game.apply(EndTurn(1)); self.portable(game, 'retire')

    def test_replacing_the_installed_power_retires_its_listener_and_original_recipe(self):
        game = self.game(hand=(CARD,RESET)); self.play(game, CARD); self.choose(game); old = self.power(game).id
        self.play(game, RESET); self.assertEqual(self.power(game).card_id, 'HERO_04bp')
        self.assertEqual(game.state.entities[old].zone, Zone.GRAVEYARD)
        board = {i:(game.state.entities[i].attack,game.state.entities[i].health) for i in game.state.players[1].board}
        game.apply(EndTurn(1))
        self.assertEqual(board,{i:(game.state.entities[i].attack,game.state.entities[i].health) for i in board})
        self.assertEqual(game.state.players[1].hand, []); self.portable(game)

    def test_actual_installation_reaction_wait_is_portable_and_nested_failure_is_atomic(self):
        game = self.game(mode='wait'); self.play(game,CARD); self.choose(game)
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.EFFECT)
        saved=game.snapshot();other=self.portable(game,'wait')
        with self.assertRaises(ResolutionError):
            game.apply(SelectChoice(1,game.state.pending_choice.id,('fail',)))
        self.assertEqual(game.snapshot(),saved)
        for value in (game,other): value.apply(SelectChoice(1,value.state.pending_choice.id,('continue',)))
        self.assertEqual(game.snapshot(),other.snapshot()); self.portable(game,'wait')

    def test_installation_reaction_failure_rolls_back_to_original_paid_assembly_offer(self):
        game=self.game(mode='fail');self.play(game,CARD);saved=game.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Intentional installed-power reaction failure'):self.choose(game)
        self.assertEqual(game.snapshot(),saved);self.assertEqual(game.state.players[1].mana,5)
        self.portable(game,'fail')

    def test_historical_battlecry_can_install_on_a_different_real_minion_carrier(self):
        game=self.game(hand=(CARD,HOST));self.play(game,CARD);self.choose(game);old=self.power(game).id
        host=self.play(game,HOST);offer=self.offer(game)
        self.assertEqual(offer.spec.source_id,host);self.assertEqual(game.state.entities[host].card_id,HOST)
        self.choose(game);self.assertNotEqual(self.power(game).id,old)
        self.assertEqual(game.state.entities[old].zone,Zone.GRAVEYARD);self.portable(game)

    def test_missing_unknown_or_incompatible_curated_content_never_becomes_a_truncated_pool(self):
        for mode in ('missing','unknown','incompatible','general-only'):
            with self.subTest(mode=mode):
                game=self.game(mode=mode);saved=game.snapshot()
                with self.assertRaises(ResolutionError):self.play(game,CARD)
                self.assertEqual(game.snapshot(),saved)

    def test_pure_implicit_catalog_keeps_complete_selected_recipe_and_never_registers_a_blank_template(self):
        registry=fixture();recipe=AssembledPowerRecipe(POWER,AssembleRecipe(DANCER,YESTERLOC,'bottom').card_id)
        fingerprint=registry.fingerprint();count=len(registry.cards)
        self.assertEqual(power_recipe_from_id(recipe.card_id),recipe)
        self.assertEqual(registry.cards[recipe.card_id],registry.card(recipe.card_id))
        self.assertIn(recipe.card_id,registry.cards)
        self.assertEqual((len(registry.cards),registry.fingerprint()),(count,fingerprint))
        with self.assertRaises(UnsupportedDefinitionError):registry.card(POWER)
        bad=AssembledPowerRecipe(POWER,AssembleRecipe('CORE_UNG_809','CORE_EX1_096','bottom').card_id)
        with self.assertRaises(UnsupportedDefinitionError):registry.card(bad.card_id)

    def test_source_bound_requests_cannot_mix_hand_rewards_or_rewrite_curated_pool(self):
        spec=Assemble(1,POOL,1,passive_power_template_id=POWER)
        for kwargs in (dict(source_id=None),dict(cost=CostSpec(delta=-1)),dict(primary_query=PoolQuery(class_mode='other',include_neutral=False)),dict(secondary_min_cost=5)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):replace(spec,**kwargs)
        game=self.game();self.play(game,CARD);offer=self.offer(game)
        with self.assertRaises(ValueError):validate_offer(game.registry,CTX,replace(offer,spec=replace(offer.spec,pool_id='constructed.assemble')))

    def test_rehashed_pending_template_change_or_trimmed_outcome_is_rejected(self):
        game=self.game();self.play(game,CARD);saved=game.snapshot()
        def nodes(value):
            if isinstance(value,dict):
                yield value
                for item in value.values():yield from nodes(item)
            elif isinstance(value,list):
                for item in value:yield from nodes(item)
        for mode in ('template','trim'):
            bad=deepcopy(saved)
            if mode=='trim':bad['state']['pending_choice']['options'].pop()
            else:
                changed=0
                for node in nodes(bad):
                    fields=node.get('fields',{})
                    if fields.get('passive_power_template_id')==POWER:
                        fields['passive_power_template_id']=None;changed+=1
                self.assertGreater(changed,0)
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in('schema_version','events','events_hash','state_hash')})
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture())

    def test_registered_template_is_immutable_and_profile_material_is_not_a_static_substitute(self):
        registry=fixture();registry.freeze();profile=registry.assembled_power_profiles[POWER]
        with self.assertRaises(ValueError):registry.register_assembled_power_profile(profile)
        with self.assertRaises(TypeError):registry.assembled_power_profiles[POWER]=profile
        self.assertEqual(profile.source_card_id,CARD);self.assertEqual(profile.pool_id,POOL)
        self.assertEqual(canonical_digest(asdict(profile.metadata)),canonical_digest(asdict(registry.card(
            AssembledPowerRecipe(POWER,AssembleRecipe(DANCER,YESTERLOC,'bottom').card_id).card_id).metadata)))

    def test_player_command_selects_passive_preview_without_exposing_full_private_offer(self):
        game=self.game();self.play(game,CARD);saved=game.snapshot()
        for seat in (1,2):
            public=json.dumps(game.for_player(seat).observe())+json.dumps(game.player_events(seat))
            for hidden in ('primary_candidates','secondary_candidates','rng_before','rng_after','assembled_power_profiles'):
                self.assertNotIn(hidden,public)
        self.assertEqual(game.snapshot(),saved)
        listing=game.for_player(1).legal_actions();action=next(a for a in listing['actions']if a['type']=='select_choice')
        self.assertTrue(game.for_player(1).submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertTrue(self.power(game).card_id.startswith('assemble-power:'));self.portable(game)


if __name__=='__main__':unittest.main()
