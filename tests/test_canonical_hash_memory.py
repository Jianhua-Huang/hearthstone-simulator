"""Identical canonical digests with a bounded fallback after allocation failure."""
import hashlib
import json
import unittest
import weakref
from unittest.mock import patch

from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine import serialization as wire
from test_engine_replay import make_registry


class CanonicalHashMemoryTests(unittest.TestCase):
    def expected(self,value):
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
            separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()

    def test_stream_fallback_matches_all_scalar_escape_and_number_encodings(self):
        values=[None,True,False,0,-1,10**80,0.0,-0.0,1.2345678901234567,1e-200,
            '\0\n\t"\\游戏😀',[],{},({'z':[None,True,3.0],'a':('中',-0.0)},)]
        expected=[self.expected(v)for v in values]
        with patch.object(wire.json,'dumps',side_effect=MemoryError('injected allocation failure')):
            self.assertEqual([wire.canonical_hash(v)for v in values],expected)

    def test_large_unicode_strings_keep_complete_content_and_same_digest(self):
        value={'large':'火😀\\"\n'*20000,'nested':[{'value':i}for i in range(500)]}
        expected=self.expected(value)
        with patch.object(wire.json,'dumps',side_effect=MemoryError):
            self.assertEqual(wire.canonical_hash(value),expected)

    def test_utf8_allocation_failure_also_uses_the_same_streaming_contract(self):
        value={'a':'中'*40000};expected=self.expected(value);original=json.dumps
        class NoFullEncode(str):
            def encode(self,*args,**kwargs):raise MemoryError('whole UTF-8 buffer')
        with patch.object(wire.json,'dumps',side_effect=lambda *a,**k:NoFullEncode(original(*a,**k))):
            self.assertEqual(wire.canonical_hash(value),expected)

    def test_failed_encoder_frame_is_released_before_streaming(self):
        refs=[];original=wire.json.JSONEncoder.iterencode
        class Marker:pass
        def fail(*args,**kwargs):
            marker=Marker();refs.append(weakref.ref(marker));raise MemoryError('frame owns marker')
        def stream(encoder,value,*args,**kwargs):
            self.assertIsNone(refs[0]())
            return original(encoder,value,*args,**kwargs)
        expected=self.expected({'a':1})
        with patch.object(wire.json,'dumps',side_effect=fail),patch.object(wire.json.JSONEncoder,'iterencode',stream):
            self.assertEqual(wire.canonical_hash({'a':1}),expected)

    def test_fallback_still_rejects_non_json_nan_cycles_and_invalid_unicode(self):
        cyclic=[];cyclic.append(cyclic)
        for value,error in ((float('nan'),ValueError),(float('inf'),ValueError),({1,2},TypeError),
                            (cyclic,ValueError),('\ud800',UnicodeEncodeError),({1:0,'x':1},TypeError)):
            with self.subTest(value_type=type(value).__name__),patch.object(wire.json,'dumps',side_effect=MemoryError):
                with self.assertRaises(error):wire.canonical_hash(value)

    def test_real_snapshot_and_player_command_keep_full_hashes_and_restore(self):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('soldier',),mana=5,max_mana=5),PlayerSetup('hero'))),make_registry())
        expected=g.snapshot();original=json.dumps
        def limited(value,*args,**kwargs):
            if isinstance(value,dict)and 'rng_state'in value and 'ruleset'in value:raise MemoryError('snapshot payload buffer')
            return original(value,*args,**kwargs)
        with patch.object(wire.json,'dumps',side_effect=limited):
            self.assertEqual(g.snapshot(),expected)
            port=g.for_player(1);legal=port.legal_actions()
            action=next(a for a in legal['actions']if a['type']=='play_card')
            reply=port.submit({'revision':legal['revision'],'action':action})
            self.assertTrue(reply['accepted'])
            after=g.snapshot()
        self.assertEqual(g.snapshot(),after)
        self.assertEqual(Game.from_snapshot(after,make_registry()).snapshot(),after)

    def test_stream_allocation_failure_is_propagated_without_mutating_the_match(self):
        g=Game.from_scenario(Scenario((PlayerSetup('hero'),PlayerSetup('hero'))),make_registry());before=g.snapshot()
        original=json.dumps
        original_iter=wire.json.JSONEncoder.iterencode
        def limited(value,*args,**kwargs):
            if isinstance(value,dict)and 'rng_state'in value:raise MemoryError('snapshot payload')
            return original(value,*args,**kwargs)
        def exhausted(encoder,value,*args,**kwargs):
            if isinstance(value,dict)and 'rng_state'in value:raise MemoryError('also exhausted')
            return original_iter(encoder,value,*args,**kwargs)
        with patch.object(wire.json,'dumps',new=limited),patch.object(wire.json.JSONEncoder,'iterencode',exhausted):
            with self.assertRaises(MemoryError):g.snapshot()
        self.assertEqual(g.snapshot(),before)
