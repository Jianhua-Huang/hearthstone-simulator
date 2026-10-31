"""Reflection reuse and wire capture preserve strict typing and the original wire."""
from dataclasses import asdict, dataclass
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine import continuations, serialization
from hs_sim.engine.resolver import Mechanics, default_mechanics


@dataclass(frozen=True)
class ExtensionPayload:
    count: int


def game():
    r=Registry('wire-performance-test')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=2,health=3))
    r.register_behavior('ask',lambda c:(RequestChoice(c.player_id,
        (ChoiceOption('ok','OK',(GainArmor(c.player_id,2),)),),source_id=c.source_id),))
    r.register_card(CardDefinition('ask','Ask',CardType.SPELL,on_play='ask'))
    return Game.from_scenario(Scenario((PlayerSetup('hero',hand=('ask',),board=('plain',),mana=10,max_mana=10),
        PlayerSetup('hero',board=('plain',))),seed=13),r)


def original_wire(state):
    # Frozen pre-optimization control: whole-state asdict followed by the exact
    # original specialized overrides. This deliberately does extra work.
    from hs_sim.engine.whole_card_replay_state import encode
    result=asdict(state)
    result['temporary_power_returns']={str(k):asdict(v)for k,v in sorted(state.temporary_power_returns.items())}
    result['whole_card_replay_ledger']=encode(state.whole_card_replay_ledger)
    result['players']={str(k):asdict(v)for k,v in sorted(state.players.items())}
    for row,batch in zip(result['end_turn_batches'],state.end_turn_batches):
        if batch.event is not None:row['event']=serialization.event_to_dict(batch.event)
    for row,record in zip(result['end_turn_history'],state.end_turn_history):
        if record.guard_event is not None:row['guard_event']=serialization.event_to_dict(record.guard_event)
    for row,record in zip(result['ability_trigger_history'],state.ability_trigger_history):
        if record.request.native_event is not None:row['request']['native_event']=serialization.event_to_dict(record.request.native_event)
    for row,receipt in zip(result['resource_operations'],state.resource_operations):
        row['event']=serialization.event_to_dict(receipt.event)
    result['entities']={str(k):serialization.entity_to_dict(v)for k,v in sorted(state.entities.items())}
    return json.loads(json.dumps(result,ensure_ascii=False,allow_nan=False))


class FrameMetadataPerformanceTests(unittest.TestCase):
    def test_core_type_reflection_reused_but_each_value_still_checked(self):
        codec=FrameCodec(default_mechanics(),Registry('codec-test'))
        with patch.object(continuations,'get_type_hints',wraps=continuations.get_type_hints)as hints:
            encoded=codec.encode((GainArmor(1,1),GainArmor(1,2)))
            self.assertEqual(codec.decode(encoded),(GainArmor(1,1),GainArmor(1,2)))
            self.assertEqual(sum(c.args[0]is GainArmor for c in hints.call_args_list),1)
        invalid=json.loads(json.dumps(encoded['tuple'][0]))
        invalid['fields']['amount']=True
        with self.assertRaises(ValueError):codec.decode(invalid)

    def test_external_schema_resolution_remains_live(self):
        mechanics=Mechanics('extension-codec-test');mechanics.register_payload_type(ExtensionPayload)
        codec=FrameCodec(mechanics,Registry('extension-codec-test'))
        codec.encode(ExtensionPayload(2))
        original=dict(ExtensionPayload.__annotations__)
        try:
            ExtensionPayload.__annotations__['count']=str
            with self.assertRaises(ValueError):codec.encode(ExtensionPayload(2))
        finally:
            ExtensionPayload.__annotations__.clear();ExtensionPayload.__annotations__.update(original)

    def test_core_annotation_change_does_not_use_stale_reflection(self):
        codec=FrameCodec(default_mechanics(),Registry('codec-test'));codec.encode(GainArmor(1,1))
        original=dict(GainArmor.__annotations__)
        try:
            GainArmor.__annotations__['amount']=str
            with self.assertRaises(ValueError):codec.encode(GainArmor(1,1))
        finally:
            GainArmor.__annotations__.clear();GainArmor.__annotations__.update(original)

    def test_extension_without_importable_module_retains_original_codec_support(self):
        original=ExtensionPayload.__module__
        try:
            ExtensionPayload.__module__=None
            mechanics=Mechanics('anonymous-extension-test');mechanics.register_payload_type(ExtensionPayload)
            codec=FrameCodec(mechanics,Registry('anonymous-extension-test'))
            self.assertEqual(codec.decode(codec.encode(ExtensionPayload(2))),ExtensionPayload(2))
        finally:
            ExtensionPayload.__module__=original

    def test_cached_metadata_does_not_allow_unknown_fields_or_extra_depth(self):
        codec=FrameCodec(default_mechanics(),Registry('codec-test'));row=codec.encode(GainArmor(1,1))
        row['fields']['unknown']=1
        with self.assertRaises(ValueError):codec.decode(row)
        value=1
        for _ in range(70):value=(value,)
        with self.assertRaises(ValueError):codec.encode(value)

    def test_snapshot_captures_payload_once_and_preserves_restore(self):
        g=game()
        with patch.object(g,'_hash_payload',wraps=g._hash_payload)as capture:
            saved=g.snapshot();self.assertEqual(capture.call_count,1)
        self.assertEqual(saved['state_hash'],g.state_hash())
        self.assertEqual(Game.from_snapshot(saved,g.registry).snapshot(),saved)

    def test_complete_wire_and_key_order_match_original_encoder(self):
        g=game()
        for boundary in range(3):
            expected=original_wire(g._state)
            actual=serialization.state_to_dict(g._state)
            self.assertEqual(json.dumps(actual,ensure_ascii=False),json.dumps(expected,ensure_ascii=False))
            self.assertEqual(list(actual),list(expected))
            actual['players']['1']['mana']=-999
            self.assertNotEqual(g._state.players[1].mana,-999)
            if boundary==0:g.apply(PlayCard(1,g._state.players[1].hand[0]))
            elif boundary==1:
                choice=g._state.pending_choice
                g.apply(SelectChoice(1,choice.id,(choice.options[0].id,)))


if __name__=='__main__':unittest.main()
