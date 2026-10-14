"""Public non-damage debit floor combinations. Local contracts, not CN proof."""
from copy import deepcopy
from pathlib import Path
import json, os, unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game,
    GrantHealthLossFloor, HealthLossFloorSpec, HealthLossKind, HealthLossReplacementSpec,
    Keyword, LoseHealth, PaymentType, PlayCard, PlayerSetup, Registry, ResolutionError,
    RewindSpec, Scenario, SelectChoice, SnapshotError, StatRelationSpec, TriggerSpec, Zone,
    loss_floor_result)
from hs_sim.engine.effects import (AddCostModifier, Buff, ChangeControl, ChoiceOption,
    CopyMinion, Damage, Destroy, EquipWeapon, GainArmor, RandomDamage, RequestChoice,
    SetStats, Silence, Summon, Transform)
from hs_sim.engine.health_loss import ChangeHeroMaxHealth
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell


def registry():
    r = Registry('v156-effect-current-health-debit-floor-local')
    self1 = HealthLossFloorSpec()
    friend3 = HealthLossFloorSpec(3, target_relation='friendly')
    for card in (
        CardDefinition('hero', 'Hero', CardType.HERO, health=30),
        CardDefinition('floorhero', 'Hero floor', CardType.HERO, health=30,
            health_loss_floors=(HealthLossFloorSpec(28),)),
        CardDefinition('shieldhero', 'Protected Hero', CardType.HERO, health=30,
            keywords=(Keyword.IMMUNE, Keyword.DIVINE_SHIELD), health_loss_floors=(HealthLossFloorSpec(28),)),
        CardDefinition('body', 'Body', CardType.MINION, health=5, attack=2),
        CardDefinition('floor', 'Own floor', CardType.MINION, health=5, health_loss_floors=(self1,)),
        CardDefinition('over', 'Over max floor', CardType.MINION, health=5, health_loss_floors=(HealthLossFloorSpec(100),)),
        CardDefinition('provider', 'Two independent floors', CardType.MINION, health=5,
            health_loss_floors=(HealthLossFloorSpec(1, target_relation='friendly'), friend3)),
        CardDefinition('replace', 'Replacement', CardType.MINION, health=5,
            health_loss_replacements=(HealthLossReplacementSpec(),)),
        CardDefinition('derived', 'Derived', CardType.MINION, health=5, attack=9,
            health_loss_floors=(self1,), stat_relations=(StatRelationSpec(),)),
        CardDefinition('reborn', 'Reborn', CardType.MINION, health=5,
            health_loss_floors=(self1,), keywords=(Keyword.REBORN,)),
    ):
        r.register_card(card)

    def after_loss(c):
        # A real captured ordinary trigger retains its original event/context.
        if c.event.target_id == c.source_id:
            return []
        return [Transform(c.source_id, 'body'), RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),), c.source_id)]
    r.register_behavior('after_loss', after_loss)
    r.register_card(CardDefinition('waiting_provider', 'Floor source with reaction', CardType.MINION, health=5,
        health_loss_floors=(friend3,), triggers=(TriggerSpec('health_lost', 'after_loss'),)))

    def waiting(c):
        bad = (GrantHealthLossFloor(c.target_id, HealthLossFloorSpec(3), c.source_id),
            LoseHealth(c.target_id, 9, c.source_id), RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
            EquipWeapon(1, 'body'))
        good = (GrantHealthLossFloor(c.target_id, HealthLossFloorSpec(3), c.source_id), LoseHealth(c.target_id, 9, c.source_id))
        return [RequestChoice(1, (ChoiceOption('bad', 'Failure', bad), ChoiceOption('ok', 'Debit', good)), c.source_id)]

    def retry(c):
        return [Summon(1, 'provider'), CastSpell(1, 'own_loss', c.source_id, choices='player')]
    bodies = {
        'ordered': lambda c: [LoseHealth(c.target_id, 3, c.source_id), LoseHealth(c.target_id, 9, c.source_id)],
        'loss9': lambda c: [LoseHealth(c.target_id, 9, c.source_id)],
        'loss0': lambda c: [LoseHealth(c.target_id, 0, c.source_id)],
        'own_loss': lambda c: [LoseHealth(c.state.players[1].hero_id, 9, c.source_id)],
        'injure': lambda c: [Damage(c.target_id, 3, c.source_id)],
        'damage9': lambda c: [Damage(c.target_id, 9, c.source_id)],
        'silence': lambda c: [Silence(c.target_id)],
        'transform': lambda c: [Transform(c.target_id, 'body')],
        'kill': lambda c: [Destroy(c.target_id, c.source_id)],
        'grant': lambda c: [GrantHealthLossFloor(c.target_id, HealthLossFloorSpec(3), c.source_id)],
        'temp': lambda c: [GrantHealthLossFloor(c.target_id, HealthLossFloorSpec(3), c.source_id, c.state.turn)],
        'copy': lambda c: [CopyMinion(c.target_id, 1)],
        'basecopy': lambda c: [CopyMinion(c.target_id, 1, mode='base')],
        'steal': lambda c: [ChangeControl(c.target_id, 2)],
        'negative': lambda c: [Buff(c.target_id, health=-9, source_id=c.source_id)],
        'set': lambda c: [SetStats(c.target_id, health=2, source_id=c.source_id)],
        'max': lambda c: [ChangeHeroMaxHealth(1, -29, c.source_id)],
        'setup_pay': lambda c: [AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH), 1)],
        'paid_choice': lambda c: [RequestChoice(1, (ChoiceOption('ok', 'Paid', (GainArmor(1, 1),)),), c.source_id)],
        'waiting': waiting,
        'retry': retry,
    }
    for name, body in bodies.items():
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=2 if name == 'paid_choice' else 0,
            on_play=name, requires_target=name not in ('own_loss', 'setup_pay', 'paid_choice', 'retry', 'max'),
            keywords=(Keyword.REWIND,) if name == 'retry' else (), rewind=RewindSpec(1) if name == 'retry' else None))
    return r


class EffectLossFloorTests(unittest.TestCase):
    def blob(self, value, label):
        if not os.environ.get('V156_INPUT_DIR'):
            return
        root = Path(os.environ['V156_INPUT_DIR'])/self._testMethodName
        root.mkdir(parents=True, exist_ok=True)
        number = getattr(self, 'input_number', 0)+1
        self.input_number = number
        (root/(f'{number:03d}-'+label+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def game(self, hand=(), board=(), enemy=(), hero='hero', armor=0):
        g = Game.from_scenario(Scenario((PlayerSetup(hero, hand=hand, board=board, mana=10,
            max_mana=10, armor=armor, deck=('body',)*8), PlayerSetup('hero', board=enemy, deck=('body',)*8)), seed=156), registry())
        self.blob(g.snapshot(), 'initial')
        return g

    def cast(self, g, name, target=None):
        self.blob(g.snapshot(), 'before-'+name)
        p = g.state.active_player
        card = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(p, card, target))

    def choose(self, g, key):
        self.blob(g.snapshot(), 'before-choice-'+key)
        c = g.state.pending_choice
        return g.apply(SelectChoice(c.player_id, c.id, (key,)))

    def values(self, g):
        return [v for e in g.events if (v := loss_floor_result(e)) is not None]

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        self.blob(s, 'portable')
        self.assertEqual(Game.from_snapshot(deepcopy(s), registry()).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        for p in (1, 2):
            public = json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for k in ('loss_floor_result', 'health_loss_floor_resolved', 'LossFloorPlan', 'replacement_ability',
                    'next_attachment_id', 'resolution_frame'):
                self.assertNotIn('"'+k+'"', public)
        return s

    def reject(self, s, label):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        self.blob(s, 'rehashed-'+label)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, registry())

    def test_ordered_losses_use_live_hp_and_actual_non_damage_events(self):
        g = self.game(('ordered',), enemy=('floor',))
        t = g.state.players[2].board[0]
        self.cast(g, 'ordered', t)
        self.assertEqual([(v.health_before, v.requested_loss, v.accepted_loss, v.prevented_by_floor, v.health_after)
            for v in self.values(g)], [(5,3,3,0,2),(2,9,1,8,1)])
        self.assertEqual([e.amount for e in g.events if e.kind == 'health_lost'], [3,1])
        self.assertFalse([e for e in g.events if e.kind in ('damage_dealt', 'healed', 'health_resolved')])
        self.portable(g)

    def test_armor_shield_immunity_unchanged_and_no_damage_pipeline(self):
        g = self.game(('loss9',), hero='shieldhero', armor=7)
        h = g.state.players[1].hero_id
        self.cast(g, 'loss9', h)
        e = g.state.entities[h]
        self.assertEqual((e.health, e.armor), (28,7))
        self.assertTrue({Keyword.IMMUNE, Keyword.DIVINE_SHIELD} <= e.keywords)
        self.assertEqual((self.values(g)[0].actual_lost, self.values(g)[0].prevented_by_floor), (2,7))
        self.assertFalse([e for e in g.events if e.kind in ('shield_lost','damage_dealt','healed')])
        self.portable(g)

    def test_replacement_grows_only_allowed_debit_and_zero_allocates_nothing(self):
        g = self.game(('loss9','loss0'), ('replace',), hero='floorhero')
        h = g.state.players[1].hero_id
        self.cast(g, 'loss9', h)
        value = self.values(g)[0]
        self.assertEqual((value.accepted_loss, value.actual_lost, value.health_replaced, value.prevented_by_floor), (2,0,2,7))
        self.assertEqual((g.state.entities[h].health, g.state.entities[h].max_health), (32,32))
        self.assertEqual([e.amount for e in g.events if e.kind == 'max_health_gained'], [2])
        n = g.state.next_attachment_id
        self.cast(g, 'loss0', h)
        self.assertEqual(g.state.next_attachment_id, n)
        self.assertEqual(self.values(g)[-1].accepted_loss, 0)
        self.portable(g)

    def test_below_or_over_max_floor_does_not_heal_or_raise_max(self):
        for body in ('floor','over'):
            g = self.game(('injure','grant','loss9'), enemy=(body,))
            t = g.state.players[2].board[0]
            self.cast(g, 'injure', t)
            self.cast(g, 'grant', t)
            old = g.state.entities[t]
            before = (old.health, old.max_health, old.damage, old.doomed)
            self.cast(g, 'loss9', t)
            self.assertEqual((old.health, old.max_health, old.damage, old.doomed), before)
            self.assertEqual(self.values(g)[-1].accepted_loss, 0)
            self.portable(g)

    def test_destroy_and_reborn_new_body_are_not_guarded(self):
        g = self.game(('loss9','kill','loss9'), enemy=('reborn',))
        old = g.state.players[2].board[0]
        self.cast(g, 'loss9', old)
        self.assertEqual(g.state.entities[old].health, 1)
        self.cast(g, 'kill', old)
        new = g.state.players[2].board[0]
        self.assertNotEqual(old,new)
        self.assertEqual(g.state.entities[new].health,1)
        self.cast(g,'loss9',new)
        self.assertEqual(self.values(g)[-1].accepted_loss,0)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_stat_and_maximum_writes_are_separate_scopes(self):
        g = self.game(('set','loss9'), enemy=('over',))
        t = g.state.players[2].board[0]
        self.cast(g,'set',t)
        self.assertEqual(g.state.entities[t].health,2)
        self.cast(g,'loss9',t)
        self.assertEqual(g.state.entities[t].health,2)
        self.portable(g)
        g = self.game(('negative',), enemy=('over',))
        t = g.state.players[2].board[0]
        self.cast(g,'negative',t)
        self.assertEqual(g.state.entities[t].zone,Zone.GRAVEYARD)
        self.portable(g)
        g = self.game(('max',),hero='floorhero')
        self.cast(g,'max')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].max_health,1)
        self.portable(g)

    def test_max_union_independent_rows_and_silence_preserve_old_receipt(self):
        g = self.game(('loss9','silence','loss9'), ('provider', 'body'))
        provider,t = g.state.players[1].board
        self.cast(g,'loss9',t)
        value = self.values(g)[0]
        self.assertEqual((value.plan.floor,len(value.plan.rows),value.accepted_loss),(3,2,2))
        self.assertNotEqual(value.plan.rows[0].ability.id,value.plan.rows[1].ability.id)
        self.cast(g,'silence',provider)
        self.cast(g,'loss9',t)
        self.assertEqual(len(self.values(g)),1)
        self.assertEqual(g.state.entities[t].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_control_retargets_new_loss_current_and_base_copy_keep_own_row_ids(self):
        g = self.game(('copy','basecopy','steal','loss9'), ('provider','body'))
        provider, t = g.state.players[1].board
        self.cast(g,'copy',provider)
        self.cast(g,'basecopy',provider)
        all_rows = [a.id for i in g.state.players[1].board for a in g.state.entities[i].abilities if a.kind == 'health_loss_floor']
        self.assertEqual(len(all_rows),len(set(all_rows)))
        self.cast(g,'steal',provider)
        self.cast(g,'loss9',t)
        self.assertEqual({row.carrier.controller for row in self.values(g)[0].plan.rows},{1})
        self.assertNotIn(provider,{row.carrier.entity_id for row in self.values(g)[0].plan.rows})
        self.portable(g)

    def test_temporary_floor_expires_and_transform_new_face_does_not_keep_it(self):
        g = self.game(('temp','loss9'), ('body',))
        t = g.state.players[1].board[0]
        self.cast(g,'temp',t)
        self.cast(g,'loss9',t)
        g.apply(EndTurn(1))
        self.assertFalse([a for a in g.state.entities[t].abilities if a.kind == 'health_loss_floor'])
        self.portable(g)
        g = self.game(('transform','loss9'),enemy=('floor',))
        t = g.state.players[2].board[0]
        self.cast(g,'transform',t)
        self.cast(g,'loss9',t)
        self.assertEqual(self.values(g),[])
        self.portable(g)

    def test_real_reaction_waiting_after_original_provider_transform(self):
        g = self.game(('loss9',), ('waiting_provider','body'))
        provider,t = g.state.players[1].board
        self.cast(g,'loss9',t)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[provider].card_id,'body')
        self.assertEqual(self.values(g)[0].plan.rows[0].carrier.card_id,'waiting_provider')
        self.portable(g)
        self.choose(g,'ok')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.portable(g)

    def test_paid_health_choice_uses_original_payment_not_effect_floor(self):
        g = self.game(('setup_pay','paid_choice'),hero='floorhero')
        self.cast(g,'setup_pay')
        self.cast(g,'paid_choice')
        self.assertIsNotNone(g.state.pending_choice)
        h = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(h.health,28)
        self.assertEqual(self.values(g),[])
        self.portable(g)
        self.choose(g,'ok')
        h = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((h.health,h.armor),(28,1))
        self.portable(g)

    def test_waiting_failure_after_debit_and_rng_restores_complete_original_state(self):
        g = self.game(('waiting',),enemy=('body',))
        t = g.state.players[2].board[0]
        self.cast(g,'waiting',t)
        before = self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.portable(g)
        self.choose(g,'ok')
        self.assertEqual((g.state.entities[t].health,self.values(g)[0].accepted_loss),(3,2))
        self.portable(g)

    def test_true_retry_deletes_generated_source_and_keeps_old_result_facts(self):
        g = self.game(('retry',),hero='floorhero')
        self.cast(g,'retry')
        self.assertIsNotNone(g.state.pending_choice)
        first = self.values(g)[0]
        source, carrier = first.plan.source.entity_id, first.plan.rows[-1].carrier.entity_id
        self.portable(g)
        self.choose(g,'retry')
        self.assertNotIn(source,g.state.entities)
        self.assertNotIn(carrier,g.state.entities)
        self.assertEqual(len(self.values(g)),2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
        self.portable(g)

    def test_derived_attack_reads_floor_limited_health_without_cache(self):
        g = self.game(('loss9',),enemy=('derived',))
        t = g.state.players[2].board[0]
        self.assertEqual(g.state.entities[t].attack,5)
        self.cast(g,'loss9',t)
        self.assertEqual((g.state.entities[t].health,g.state.entities[t].attack),(1,1))
        self.portable(g)

    def test_closed_specs_unknown_boolean_and_payment_scope_reject(self):
        for kwargs in ({'floor':True},{'floor':0},{'floor':-1},{'kinds':(HealthLossKind.PAYMENT,)},
                {'kinds':('effect',)},{'target_relation':'mystery'},{'target_kinds':(CardType.SPELL,)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                HealthLossFloorSpec(**kwargs)
        r = registry()
        with self.assertRaises(ValueError):
            r.register_card(CardDefinition('unknown','Unknown',CardType.SPELL,health_loss_floors=(HealthLossFloorSpec(),)))

    def test_rehashed_original_allocation_row_type_and_conservation_negatives(self):
        g = self.game(('loss9',),enemy=('floor','floor'))
        t = g.state.players[2].board[0]
        self.cast(g,'loss9',t)
        snap = self.portable(g)
        event_index = next(i for i,e in enumerate(snap['events']) if e['kind'] == 'health_loss_floor_resolved')
        def set_pair(rows,name,value):
            next(row for row in rows if row[0] == name)[1] = value
        mutations = ('future_target','future_row','borrowed_row','unknown_face','boolean_floor','extra_field','bad_conservation')
        for which in mutations:
            s = deepcopy(snap)
            payload = s['events'][event_index]['data']['loss_floor_result']
            p = dict(payload)['plan']; pd = dict(p)
            rows = dict(pd['rows'][0]); a = rows['ability']; c = rows['carrier']
            if which == 'future_target': set_pair(pd['target'],'entity_id',s['state']['next_entity_id'])
            elif which == 'future_row': set_pair(a,'id',s['state']['next_attachment_id'])
            elif which == 'borrowed_row':
                other = g.state.players[2].board[1]
                set_pair(a,'id',next(a.id for a in g.state.entities[other].abilities if a.kind == 'health_loss_floor'))
            elif which == 'unknown_face': set_pair(c,'card_id','unknown-native-face')
            elif which == 'boolean_floor': set_pair(p,'floor',True)
            elif which == 'extra_field': p.append(['unknown',0])
            elif which == 'bad_conservation': set_pair(payload,'accepted_loss',0)
            self.reject(s,which)


if __name__ == '__main__':
    unittest.main()
