"""Frozen identity reuse never hides changed declarations or unknown extensions."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from hs_sim.engine import CardDefinition, CardType, CostAuraSpec, CostSpec, Game, PlayerSetup, Registry, Scenario, SnapshotError
from hs_sim.engine import registry as registry_module
from hs_sim.engine import model


def registry():
    r=Registry('guarded-registry-identity')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('aura','Aura',CardType.MINION,health=2,
        cost_auras=(CostAuraSpec(CostSpec(delta=1)),)))
    return r


class RegistryIdentityPerformanceTests(unittest.TestCase):
    def test_complete_constructed_inventory_reuses_exact_original_identity(self):
        from hs_sim.local_pool_format import build_cn37_local_pool_format
        r=build_cn37_local_pool_format().registry
        expected=r.fingerprint()
        r.freeze();self.assertIsNotNone(r._identity_guard)
        self.assertEqual(r.fingerprint(),expected)
        with patch.object(Registry,'validate',side_effect=AssertionError('repeat full validation')), \
                patch.object(registry_module,'asdict',side_effect=AssertionError('repeat serialization')):
            r.freeze();self.assertEqual(r.fingerprint(),expected)

    def test_unchanged_freeze_and_identity_reuse_original_complete_digest(self):
        r=registry();before=r.fingerprint();r.freeze()
        self.assertEqual(r.fingerprint(),before)
        with patch.object(Registry,'validate',side_effect=AssertionError('repeat full validation')), \
                patch.object(registry_module,'asdict',side_effect=AssertionError('repeat serialization')):
            r.freeze();self.assertEqual(r.fingerprint(),before)

    def test_explicit_validate_still_checks_every_definition(self):
        r=registry();r.freeze();r.fingerprint()
        r._cards['aura']=replace(r.card('aura'),cost=True)
        with self.assertRaises(ValueError):r.validate()

    def test_mutable_building_recomputes_and_freeze_still_rejects_registration(self):
        r=registry();first=r.fingerprint()
        r.register_card(CardDefinition('later','Later',CardType.MINION,health=1))
        second=r.fingerprint();self.assertNotEqual(first,second)
        r.freeze();self.assertEqual(r.fingerprint(),second)
        with self.assertRaises(ValueError):r.register_card(CardDefinition('blocked','Blocked',CardType.SPELL))

    def test_replaced_frozen_row_invalidates_identity_and_old_restore(self):
        r=registry();g=Game.from_scenario(Scenario((PlayerSetup('hero'),PlayerSetup('hero'))),r)
        saved=g.snapshot();old=r.fingerprint()
        r._cards['aura']=replace(r.card('aura'),cost=2)
        self.assertNotEqual(r.fingerprint(),old)
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,r)

    def test_nested_core_record_change_is_not_hidden_by_outer_identity(self):
        r=registry();r.freeze();old=r.fingerprint()
        nested=r.card('aura').cost_auras[0].cost
        object.__setattr__(nested,'delta',2)
        expected=registry();object.__setattr__(expected.card('aura').cost_auras[0].cost,'delta',2)
        self.assertEqual(r.fingerprint(),expected.fingerprint())
        self.assertNotEqual(r.fingerprint(),old)

    def test_equal_boolean_cannot_impersonate_original_integer(self):
        r=registry();r.freeze();r.fingerprint()
        nested=r.card('aura').cost_auras[0].cost
        object.__setattr__(nested,'delta',True)
        with self.assertRaises(ValueError):r.fingerprint()
        with self.assertRaises(ValueError):r.freeze()

    def test_nested_containers_are_guarded_even_without_changing_digest(self):
        r=registry();r._probe={'values':[1],'ids':{'original'}};r.freeze();old=r.fingerprint()
        original=Registry.validate;calls=[]
        def validate(current):calls.append(current);return original(current)
        with patch.object(Registry,'validate',validate):
            r._probe['values'][0]=True
            self.assertEqual(r.fingerprint(),old);self.assertEqual(len(calls),1)
            r._probe['ids'].add('later')
            self.assertEqual(r.fingerprint(),old);self.assertEqual(len(calls),2)

    def test_changed_core_post_init_is_revalidated(self):
        r=registry();r.freeze();r.fingerprint()
        with patch.object(CostSpec,'__post_init__',side_effect=ValueError('changed validation')):
            with self.assertRaisesRegex(ValueError,'changed validation'):r.fingerprint()

    def test_changed_core_owner_binding_is_revalidated(self):
        r=registry();r.freeze();r.fingerprint()
        with patch.object(model,'CostSpec',object()):
            with self.assertRaises(ValueError):r.fingerprint()

    def test_changed_core_field_schema_is_not_hidden_by_cached_identity(self):
        r=registry();r.freeze();r.fingerprint()
        field=CostSpec.__dataclass_fields__['delta'];original=field.name
        try:
            field.name='missing_delta'
            with self.assertRaises((AttributeError,ValueError)):r.fingerprint()
        finally:field.name=original

    def test_unknown_callbacks_preserve_live_path_without_extra_hooks(self):
        class Extension:
            def __call__(self,context):return ()
            def __eq__(self,other):raise AssertionError('extension equality')
            def __reduce__(self):raise AssertionError('extension reducer')
            def __deepcopy__(self,memo):raise AssertionError('extension copy')
        for module in (None,'hs_sim.engine.not_imported'):
            with self.subTest(module=module):
                Extension.__module__=module
                r=registry();r.register_behavior('extension',Extension());r.freeze()
                self.assertIsNone(r._identity_guard)
                original=Registry.validate;calls=[]
                def validate(current):calls.append(current);return original(current)
                with patch.object(Registry,'validate',validate):
                    self.assertEqual(r.fingerprint(),r.fingerprint())
                self.assertEqual(len(calls),2)

    def test_separate_registries_never_share_identity_cache(self):
        a=registry();b=registry();a.freeze();b.freeze()
        original=a.fingerprint();self.assertEqual(original,b.fingerprint())
        b._cards['aura']=replace(b.card('aura'),cost=3)
        self.assertNotEqual(b.fingerprint(),original)
        self.assertEqual(a.fingerprint(),original)


if __name__=='__main__':unittest.main()
