"""Real fourteen-member Rajh offers, native subjects and passive carrier lives."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.rajh_known_passive_pool import CARD, POWER, POOL, load_batch
from hs_sim.cards.assemble_spell_play_followups import MEDIC
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayerSetup, ResolutionError, Scenario, SnapshotError,
    SpellSchool, TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.assemble_faces import recipe_from_id
from hs_sim.engine.assemble_offers import ResolveAssemble, recipe_options
from hs_sim.engine.assembled_powers import power_recipe_from_id
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, Destroy, Draw,
    InvokeBehavior, ReplaceHeroPower, RequestChoice)
from hs_sim.engine.pools import sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.local_pool_format import build_cn37_local_pool_format, load_bindings
from hs_sim.targets import canonical_digest
from test_current_deck_empty_basics import rehash
from tools import card_batch as batch

P = 'k571.'
UNIT, DEMON, HURT, SPELL, HOLY, DRAW, ADD, ARM, RESET, KILL, HIT, WATCH, FAULT = (
    P+x for x in ('unit','demon','hurt','spell','holy','draw','add','attack','reset','kill','hit','watch','fault'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt = build_cn37_local_pool_format(); r = fmt.registry
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=20,
        metadata=replace(META, tribes=('beast',))))
    r.register_card(CardDefinition(DEMON, DEMON, CardType.MINION, attack=1, health=20,
        metadata=replace(META, tribes=('demon',))))
    def hurt(c):
        return (Damage(c.state.players[c.player_id].board[0], 1, c.source_id),
            Damage(c.state.players[c.player_id].hero_id, 1, c.source_id))
    def kill(c):
        target = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD)
        return (Destroy(target, c.source_id),)
    def fail(c):
        raise ResolutionError('k571 deliberate original passive reaction failure')
    for cid, body in (
        (HURT, hurt), (SPELL, lambda c: ()), (HOLY, lambda c: ()),
        (DRAW, lambda c: (Draw(c.player_id, source_id=c.source_id),)),
        (ADD, lambda c: (AddToHand(c.player_id, UNIT, c.source_id),)),
        (ARM, lambda c: (Buff(c.state.players[c.player_id].hero_id, attack=1,
            expires_turn=c.state.turn, source_id=c.source_id),)),
        (RESET, lambda c: (ReplaceHeroPower(c.player_id, 'HERO_04bp', source_id=c.source_id),)),
        (KILL, kill), (HIT, lambda c: (Damage(c.target_id, 1, c.source_id),))):
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            spell_school=SpellSchool.HOLY if cid == HOLY else None,
            targeting=TargetSpec() if cid == HIT else None))
    r.register_behavior(FAULT, fail)
    def watch(c):
        if c.event.kind == 'hero_power_replaced':
            target = c.state.entities[c.event.target_id]
            applicable = mode == 'install-wait' and target.card_id.startswith('assemble-power:')
        else:
            target = c.state.entities[c.event.target_id]
            applicable = mode == 'body-wait' and target.card_id == 'TTN_843t1'
        if not applicable:
            return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fault', 'Fail', (InvokeBehavior(FAULT, c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
        triggers=(TriggerSpec('hero_power_replaced', WATCH), TriggerSpec('minion_summoned', WATCH))))
    r.validate()
    if mode == 'missing':
        r._cards.pop('CORE_RLK_083')
    return r, fmt


@lru_cache(None)
def seed_for(primary, secondary):
    r, fmt = fixture(); pool = r.pool(POOL, fmt.context)
    first = tuple(sorted((m for m in pool.members if r.card(m.card_id).kind == CardType.MINION), key=lambda m:m.card_id))
    cost = r.card(primary).cost
    second = tuple(sorted((m for m in pool.members if (8 if cost in (9,10) else cost) <= r.card(m.card_id).cost <= cost+2
        and recipe_options(r, primary, m.card_id, POWER)), key=lambda m:m.card_id))
    for seed in range(10000):
        rng = Random(seed)
        if sample_candidates(rng, first, 1, replacement=False) == (primary,) and secondary in sample_candidates(rng, second, 2, replacement=False):
            return seed
    raise AssertionError('No original full-domain seed for ' + primary + '/' + secondary)


class RajhKnownPassivePoolTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role)[0])

    def game(self, primary='TLC_623', secondary='CORE_RLK_083', *, mode='normal', hand=(), player=1, seed=None):
        self.mode = mode; r, fmt = fixture(mode)
        own = PlayerSetup('HERO_04', hero_power_card_id='HERO_04bp',
            hand=(HURT, CARD) + hand, board=(UNIT, DEMON) + ((WATCH,) if 'wait' in mode else ()),
            deck=(UNIT,)*12, mana=20, max_mana=20, mana_cap=20)
        other = PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=(HIT, SPELL),
            board=(UNIT, DEMON), deck=(UNIT,)*12, mana=10, max_mana=10)
        players = (own, other) if player == 1 else (other, own)
        return Game.from_scenario(Scenario(players, active_player=player,
            seed=seed_for(primary, secondary) if seed is None else seed, generation_context=fmt.context), r)

    def offer(self, g):
        return next(e.offer for option in g._frame.options for e in option.effects if isinstance(e, ResolveAssemble))

    def install(self, g, primary, secondary, half='bottom', *, player=1):
        self.play(g, HURT, player=player); source = self.play(g, CARD, player=player)
        offer = self.offer(g)
        self.assertEqual(offer.primary_card_id, primary)
        self.assertIn(secondary, offer.secondary_card_ids)
        option = next(o for o in g.state.pending_choice.options
            if (lambda recipe: recipe.secondary_card_id == secondary and recipe.half == half)(
                recipe_from_id(power_recipe_from_id(o.card_id).minion_card_id)))
        self.choose(g, option.id)
        self.assertEqual(g.state.players[player].mana, 15)
        return source

    def power(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_power_id]

    def enemy_damage(self, g):
        p = g.state.players[2]
        return sum(g.state.entities[i].damage for i in (p.hero_id, *p.board))

    def test_full_source_roles_and_unknown_fifteenth_remain_explicit(self):
        data = load_batch(); raw = {r['id']:r for r in batch.read(data['source'])}
        for key in ('cards','existing_dependencies','evidence_only'):
            for row in data[key]:
                self.assertEqual(row['record'], raw[row['record']['id']])
        self.assertEqual((data['reported_total'], data['reported_missing_member_count']), (15,1))
        self.assertEqual(len(data['candidate_ids']),14)
        self.assertEqual(data['secondary_projection_ids'],['TLC_833'])
        self.assertFalse(data['formal_pool_complete'])
        manifest = load_bindings()
        self.assertIn(POOL,manifest['partial_inventory_pool_ids'])
        self.assertNotIn(POOL,manifest['unresolved_pool_ids'])

    def test_full_known_inventory_and_old_native_faces_and_fragments_are_preserved(self):
        r, fmt = fixture(); data = load_batch(); pool = r.pool(POOL,fmt.context)
        self.assertEqual([m.card_id for m in pool.members],data['candidate_ids'])
        self.assertTrue(pool.complete); self.assertEqual({m.weight for m in pool.members},{1})
        self.assertEqual(len(r.assembled_power_profiles[POWER].reviewed_fragment_ids),17)
        self.assertNotIn('BE_152',[m.card_id for m in pool.members])
        for row in data['existing_dependencies']:
            cid = row['record']['id']
            self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.assemble_templates.get(cid)or r.assemble_projections[cid])),row['fragment_sha256'])

    def test_all_fourteen_real_subjects_execute_after_native_offer_installation(self):
        for cid in load_batch()['candidate_ids']:
            primary = 'TLC_254' if cid == 'TLC_623' else 'TLC_623' if fixture()[0].card(cid).cost <= 4 else 'CATA_133'
            if cid == 'CATA_133':
                primary = 'TIME_100'
            with self.subTest(body=cid):
                g = self.game(primary,cid,hand=(UNIT,UNIT)); self.install(g,primary,cid)
                own = g.state.players[1]
                board = {i:(g.state.entities[i].attack,g.state.entities[i].health)for i in own.board}
                hand = tuple(own.hand); damage = self.enemy_damage(g)
                g.apply(EndTurn(1))
                own = g.state.players[1]
                bodies = [g.state.entities[i].card_id for i in own.board if i not in board]
                gained = [g.state.entities[i].card_id for i in own.hand if i not in hand]
                if cid == 'CORE_RLK_083':
                    self.assertEqual(self.enemy_damage(g)-damage,2)
                elif cid == 'TLC_623':
                    self.assertEqual(g.state.entities[next(iter(board))].attack,board[next(iter(board))][0]+2)
                elif cid == 'BE_997':
                    self.assertEqual(len(gained),1)
                    self.assertEqual(g.registry.card(gained[0]).kind,CardType.SPELL)
                    self.assertEqual(len(g.state.players[2].hand),4)
                elif cid == 'TLC_254':
                    for i in list(board)[:2]:
                        self.assertEqual(g.state.entities[i].attack,board[i][0]+1)
                elif cid == 'TLC_833':
                    self.assertEqual(bodies,['TLC_903t'])
                elif cid == 'FIR_955':
                    self.assertEqual(self.enemy_damage(g)-damage,3)
                elif cid == 'CORE_TTN_843':
                    self.assertEqual(bodies,['TTN_843t1'])
                elif cid == 'EDR_462':
                    self.assertEqual(len(gained),1)
                    self.assertTrue({'dragon','all'} & set(g.registry.card(gained[0]).metadata.tribes))
                elif cid == 'CORE_BAR_878':
                    self.assertEqual(bodies,[MEDIC])
                elif cid == 'TIME_100':
                    for i in hand:
                        self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(2,21))
                elif cid == 'CATA_133':
                    for i,(a,h) in board.items():
                        self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(a+1,h+1))
                elif cid == 'EDR_853':
                    self.assertEqual(len(bodies),1); self.assertIn(bodies[0],('NEW1_032','NEW1_033','NEW1_034'))
                elif cid == 'BE_701':
                    self.assertEqual(gained,[UNIT])
                elif cid == 'CORE_EX1_559':
                    self.assertEqual(gained,['CS2_029'])
                else:
                    self.fail('Unreviewed actual subject')
                self.assertFalse(g.state.hero_power_history)

    def test_spell_play_and_holy_subjects_keep_original_conditions(self):
        for prefix,trigger in (('CORE_RLK_083',SPELL),('CORE_BAR_878',HOLY)):
            with self.subTest(prefix=prefix):
                g = self.game('TLC_623',prefix,hand=(SPELL,HOLY)); self.install(g,'TLC_623',prefix,'top')
                target = g.state.players[1].board[0]; before = g.state.entities[target].attack
                if trigger == HOLY:
                    self.play(g,SPELL); self.assertEqual(g.state.entities[target].attack,before)
                self.play(g,trigger); self.assertEqual(g.state.entities[target].attack,before+2)

    def test_original_draw_subject_reacts_once_and_ignores_opponent_normal_draw(self):
        g = self.game('TLC_623','CORE_TTN_843',hand=(DRAW,));self.install(g,'TLC_623','CORE_TTN_843','top')
        target = g.state.players[1].board[0];before = g.state.entities[target].attack
        self.play(g,DRAW);self.assertEqual(g.state.entities[target].attack,before+2)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[target].attack,before+2)

    def test_hand_entry_subject_excludes_its_own_generated_card_and_opponent_entries(self):
        g=self.game('BE_997','EDR_462',hand=(ADD,));self.install(g,'BE_997','EDR_462')
        before=len(g.state.players[1].hand);self.play(g,ADD)
        self.assertEqual(len(g.state.players[1].hand),before+1)
        generated=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id!=UNIT]
        self.assertEqual(len(generated),1);self.assertTrue({'dragon','all'} & set(g.registry.card(generated[0].card_id).metadata.tribes))
        count=len(g.state.players[1].hand);g.apply(EndTurn(1));self.assertEqual(len(g.state.players[1].hand),count)
        self.portable(g)

    def test_hero_damage_subject_uses_real_power_liveness_and_original_owner_turn(self):
        g=self.game('FIR_955','TIME_100',hand=(HIT,UNIT));self.install(g,'FIR_955','TIME_100')
        target=self.entity(g,UNIT);self.play(g,HIT,g.state.players[1].hero_id)
        self.assertEqual((g.state.entities[target.id].attack,g.state.entities[target.id].health),(2,21))
        g.apply(EndTurn(1));self.play(g,HIT,g.state.players[1].hero_id,player=2)
        self.assertEqual((g.state.entities[target.id].attack,g.state.entities[target.id].health),(2,21))
        self.portable(g)

    def test_weapon_projection_trigger_executes_after_real_hero_attack_without_equipping_weapon(self):
        g=self.game('TLC_623','TLC_833',hand=(ARM,));self.install(g,'TLC_623','TLC_833','top')
        target=g.state.players[1].board[0];before=g.state.entities[target].attack
        self.assertIsNone(g.state.players[1].weapon_id);self.play(g,ARM)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[target].attack,before+2)
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'completed')
        self.portable(g)

    def test_minion_play_subject_includes_original_completed_rajh_then_another_minion(self):
        g=self.game('BE_701','CORE_EX1_559',hand=(UNIT,));self.install(g,'BE_701','CORE_EX1_559')
        self.assertEqual(sum(g.state.entities[i].card_id=='CS2_029'for i in g.state.players[1].hand),1)
        self.play(g,UNIT)
        self.assertEqual(sum(g.state.entities[i].card_id=='CS2_029'for i in g.state.players[1].hand),2)

    def test_successful_cast_subject_and_cast_start_subject_work_on_real_passive_carrier(self):
        for primary,secondary in (('EDR_853','CORE_EX1_559'),('CATA_133','CORE_EX1_559')):
            with self.subTest(primary=primary):
                g=self.game(primary,secondary,hand=(SPELL,));self.install(g,primary,secondary,'top')
                # The top donor is Antonidas: its actual hand-cast-start predicate.
                self.play(g,SPELL)
                if primary=='EDR_853':
                    self.assertEqual(sum(g.state.entities[i].card_id in ('NEW1_032','NEW1_033','NEW1_034')for i in g.state.players[1].board),1)
                else:
                    self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,2)
        g=self.game('EDR_853','CATA_133',hand=(SPELL,));self.install(g,'EDR_853','CATA_133')
        self.play(g,SPELL);self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,2)

    def test_keywords_do_not_attach_to_hero_and_keyword_only_changes_are_not_offered(self):
        g=self.game('TIME_100','CATA_133');self.install(g,'TIME_100','CATA_133')
        self.assertEqual(g.registry.card(self.power(g).card_id).keywords,())
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[g.state.players[1].hero_id].keywords)
        self.assertNotIn(Keyword.ELUSIVE,g.state.entities[g.state.players[1].hero_id].keywords)
        r,_=fixture();self.assertNotIn('top',[half for half,_ in recipe_options(r,'TLC_623','TIME_100',POWER)])
        self.assertNotIn('top',[half for half,_ in recipe_options(r,'TIME_100','CATA_133',POWER)])

    def test_root_death_does_not_retire_skill_but_replacement_retires_original_listener(self):
        g=self.game('BE_701','CORE_EX1_559',hand=(KILL,RESET,UNIT,UNIT));root=self.install(g,'BE_701','CORE_EX1_559')
        self.play(g,KILL);self.assertEqual(g.state.entities[root].zone,Zone.GRAVEYARD)
        self.play(g,UNIT);count=sum(g.state.entities[i].card_id=='CS2_029'for i in g.state.players[1].hand)
        old=self.power(g).id;self.play(g,RESET);self.play(g,UNIT)
        self.assertEqual(sum(g.state.entities[i].card_id=='CS2_029'for i in g.state.players[1].hand),count)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)

    def test_original_offer_installation_and_subject_waiting_restore_without_resampling(self):
        for mode in ('install-wait','body-wait'):
            with self.subTest(mode=mode):
                g=self.game('TLC_623','CORE_TTN_843',mode=mode)
                self.install(g,'TLC_623','CORE_TTN_843')
                if mode=='body-wait':g.apply(EndTurn(1))
                self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'fault')
                self.assertEqual(g.snapshot(),saved)
                for current in (g,restored):
                    while current.state.pending_choice:self.choose(current)
                self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_second_seat_and_passive_manual_use_rejection_keep_original_payment(self):
        g=self.game('TLC_623','CORE_RLK_083',player=2);self.install(g,'TLC_623','CORE_RLK_083',player=2)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(2,self.power(g,2).id))
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(2));self.assertEqual(len(g.state.hero_power_history),0)
        self.portable(g)

    def test_missing_original_member_never_truncates_known_inventory(self):
        r,fmt=fixture('missing')
        self.assertEqual(len(r.pool(POOL,fmt.context).members),14)
        with self.assertRaisesRegex((ResolutionError,UnsupportedDefinitionError),'CORE_RLK_083'):
            self.game(mode='missing')
        self.assertEqual(len(r.pool(POOL,fmt.context).members),14)

    def test_highest_cost_primary_without_known_secondaries_fails_atomically_without_pruning(self):
        r,fmt=fixture();pool=r.pool(POOL,fmt.context)
        first=tuple(sorted((m for m in pool.members if r.card(m.card_id).kind==CardType.MINION),key=lambda m:m.card_id))
        seed=next(n for n in range(1000)if sample_candidates(Random(n),first,1,replacement=False)==('CORE_EX1_559',))
        g=self.game(seed=seed);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'needs two distinct reviewed secondary'):
            self.play(g,CARD)
        self.assertEqual(g.snapshot(),saved)
        self.assertIn('CORE_EX1_559',[m.card_id for m in pool.members]);self.assertEqual(len(pool.members),14)

    def test_profile_extension_and_private_pending_material_are_strict(self):
        g=self.game();self.play(g,CARD);saved=g.snapshot()
        for player in (1,2):
            view=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            for private in ('primary_candidates','secondary_candidates','ignored_prefix_keywords','rng_before','assembled_power_profiles'):
                self.assertNotIn(private,view)
        r=build_cn37_local_pool_format().registry;profile=r.assembled_power_profiles[POWER]
        with self.assertRaises(ValueError):replace(profile,ignored_prefix_keywords=(Keyword.TAUNT,)).__post_init__()
        with self.assertRaisesRegex(ValueError,'cannot change or remove'):
            r.extend_assembled_power_profile(replace(profile,reviewed_fragment_ids=profile.reviewed_fragment_ids[1:]))
        bad=deepcopy(saved);bad['state']['pending_choice']['options'].pop()
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','independent-reader')[0])


if __name__ == '__main__':
    unittest.main()
