"""Entry bodies stay with consumed material; host lifecycle remains shared."""
from copy import deepcopy
from dataclasses import asdict,replace
import unittest
import examples.magnetic_body_lifecycle as fixture
from hs_sim.engine import Game,PlayCard,EndTurn,SelectChoice,SnapshotError,Zone
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.replay import build_replay,replay


class MagneticBodyLifecycleTests(unittest.TestCase):
    def game(self,mode='normal',multiple=False,tools=('kill',)):
        g=Game.from_scenario(fixture.scenario(mode,multiple=multiple,tools=tools),fixture.registry(mode))
        self.play(g,'setup');return g

    def play(self,g,name,target=None,viewer=1):
        source=next(i for i in g.state.players[viewer].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(viewer,source,target));return source

    def fuse(self,g):
        response=g.for_player(1).submit(fixture.paid_command(g));self.assertTrue(response['accepted'],response)

    def host(self,g):return g.state.entities[g.state.magnetic_history[0].target_id]

    def entry(self,e):return [a for a in e.abilities if a.kind in ('on_play','battlecry','combo')]

    def groups(self,e):return [a for a in (*e.enchantments,*e.abilities) if a.magnetic_id is not None]

    def armor(self,g,viewer=1):return g.state.entities[g.state.players[viewer].hero_id].armor

    def roundtrip(self,g,mode='normal'):
        snapshot=g.snapshot();observations=[g.for_player(i).observe() for i in (1,2)]
        for other in (Game.from_snapshot(snapshot,fixture.registry(mode)),g.clone(),replay(build_replay(g),fixture.registry(mode))):
            self.assertEqual(other.snapshot(),snapshot)
            self.assertEqual([other.for_player(i).observe() for i in (1,2)],observations)

    def test_printed_and_heterogeneously_granted_combo_and_battlecry_do_not_transfer(self):
        g=self.game();self.fuse(g);host=self.host(g);record=g.state.magnetic_history[-1]
        self.assertEqual([a.kind for a in self.entry(host)],['combo','battlecry'])
        self.assertTrue(all(a.magnetic_id is None for a in self.entry(host)))
        self.assertFalse(any(a.kind in ('on_play','battlecry','combo') for a in host.abilities if a.id in record.ability_ids))
        self.assertEqual(len(g.state.play_history[-1].body_targets.selected),5)
        self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.combo_history)
        self.assertEqual(g.state.players[1].mana,8);self.roundtrip(g)

    def test_material_keeps_original_entry_body_identities_without_fabricated_host_execution(self):
        g=self.game();source=next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id=='material')
        original=self.entry(source);self.fuse(g);source=g.state.entities[source.id]
        self.assertEqual(source.zone,Zone.GRAVEYARD);self.assertEqual(self.entry(source),original)
        self.assertEqual(len(original),6);self.assertFalse(g.state.death_history)

    def test_host_preexisting_entry_identities_are_unchanged(self):
        g=self.game();host=g.state.entities[g.state.players[1].board[0]];original=self.entry(host)
        self.fuse(g);self.assertEqual(self.entry(self.host(g)),original)

    def test_ongoing_trigger_deathrattle_and_keyword_still_transfer_and_execute(self):
        g=self.game();self.fuse(g);host=self.host(g)
        self.assertEqual([a.kind for a in host.abilities if a.magnetic_id is not None],['keyword','deathrattle','trigger'])
        self.play(g,'marker');self.assertEqual(self.armor(g),2)
        self.play(g,'kill',host.id);self.assertEqual(self.armor(g),5)
        self.assertEqual(len(g.state.death_history),1);self.assertFalse(g.state.combo_history)
        self.roundtrip(g)

    def test_current_copy_preserves_only_host_entry_bodies_and_independent_ongoing_ids(self):
        g=self.game(tools=('copy',));self.fuse(g);host=self.host(g);self.play(g,'copy',host.id)
        copy=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual([a.kind for a in self.entry(copy)],['combo','battlecry'])
        self.assertTrue(all(a.magnetic_id is None for a in self.entry(copy)))
        self.assertTrue({a.id for a in self.groups(host)}.isdisjoint(a.id for a in self.groups(copy)))
        self.play(g,'marker');self.assertEqual(self.armor(g),4);self.roundtrip(g)

    def test_base_copy_reinstalls_host_base_without_material_groups(self):
        g=self.game(tools=('base_copy',));self.fuse(g);self.play(g,'base_copy',self.host(g).id)
        copy=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual([a.kind for a in self.entry(copy)],['combo','battlecry']);self.assertFalse(self.groups(copy))
        self.play(g,'marker');self.assertEqual(self.armor(g),2);self.roundtrip(g)

    def test_remove_group_preserves_host_entry_bodies_and_copy_group(self):
        g=self.game(tools=('copy', 'remove'));self.fuse(g);host=self.host(g);original=self.entry(host);self.play(g,'copy',host.id)
        self.play(g,'remove',host.id);self.assertFalse(self.groups(self.host(g)));self.assertEqual(self.entry(self.host(g)),original)
        self.play(g,'marker');self.assertEqual(self.armor(g),2);self.roundtrip(g)

    def test_bounce_and_replay_execute_only_hosts_own_printed_entry_bodies(self):
        g=self.game(tools=('bounce',));self.fuse(g);host=self.host(g);self.play(g,'bounce',host.id)
        self.play(g,'host');self.assertEqual(self.armor(g),20)
        self.assertEqual([r.payload.card_id for r in g.state.combo_history],['host'])
        self.assertFalse(self.groups(g.state.entities[host.id]));self.roundtrip(g)

    def test_transform_resets_host_and_all_groups(self):
        g=self.game(tools=('transform',));self.fuse(g);host=self.host(g);self.play(g,'transform',host.id)
        host=g.state.entities[host.id];self.assertEqual(host.card_id,'fodder');self.assertFalse(self.entry(host));self.assertFalse(self.groups(host))
        self.play(g,'marker');self.assertEqual(self.armor(g),0);self.roundtrip(g)

    def test_silence_removes_material_groups_and_host_entry_bodies(self):
        g=self.game(tools=('silence',));self.fuse(g);host=self.host(g);self.play(g,'silence',host.id)
        host=g.state.entities[host.id];self.assertFalse(self.entry(host));self.assertFalse(self.groups(host))
        self.play(g,'marker');self.assertEqual(self.armor(g),0);self.roundtrip(g)

    def test_control_transfers_ongoing_execution_to_new_controller_without_entry_execution(self):
        g=self.game(tools=('control',));self.fuse(g);host=self.host(g);original=self.entry(host);self.play(g,'control',host.id)
        self.assertEqual(self.entry(g.state.entities[host.id]),original);g.apply(EndTurn(1))
        self.play(g,'marker',viewer=2);self.assertEqual(self.armor(g,2),2);self.assertEqual(self.armor(g),0)
        self.play(g,'kill',host.id,viewer=2);self.assertEqual(self.armor(g,2),5);self.assertFalse(g.state.combo_history);self.roundtrip(g)

    def test_multiple_material_groups_stack_ongoing_but_not_entry_bodies(self):
        g=self.game(multiple=True);self.fuse(g);self.play(g,'setup');self.fuse(g);host=self.host(g)
        self.assertEqual(len(g.state.magnetic_history),2);self.assertEqual(len(self.entry(host)),2)
        self.play(g,'marker');self.assertEqual(self.armor(g),4);self.roundtrip(g)

    def test_merge_wait_restore_and_resume_keep_entry_bodies_out_of_host(self):
        g=self.game('wait');self.fuse(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.entry(self.host(g))),2);self.roundtrip(g,'wait')
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('go',)))
        self.play(g,'marker');self.assertEqual(self.armor(g),2);self.roundtrip(g,'wait')

    def test_actual_merge_failure_rolls_back_all_groups_body_receipt_rng_and_payment(self):
        g=self.game('fail');command=fixture.paid_command(g);snapshot=g.snapshot();history=g.history
        self.assertFalse(g.for_player(1).submit(command)['accepted'])
        self.assertEqual(g.snapshot(),snapshot);self.assertEqual(g.history,history)

    def test_departed_host_fallback_retains_and_executes_material_entry_bodies(self):
        g=self.game('departure');self.fuse(g);play=g.state.play_history[-1]
        self.assertEqual(play.minion_result,'summoned');self.assertFalse(g.state.magnetic_history)
        self.assertEqual(len(g.state.battlecry_history)+len(g.state.combo_history),5)
        self.assertEqual(len(self.entry(g.state.entities[play.source_id])),6);self.roundtrip(g,'departure')

    def test_forged_entry_combo_in_magnetic_group_rejects_after_actual_snapshot_rehash(self):
        g=self.game();self.fuse(g);snapshot=g.snapshot();host_id=self.host(g).id
        data=snapshot['state'];record=data['magnetic_history'][0]
        body=next(a for a in data['entities'][str(record['source_id'])]['abilities'] if a['kind']=='combo')
        forged=deepcopy(body);forged.update(id=data['next_attachment_id'],origin='granted',source_id=record['source_id'],magnetic_id=record['id'])
        data['next_attachment_id']+=1;data['entities'][str(host_id)]['abilities'].append(forged)
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaisesRegex(SnapshotError,'entry-only ability'):Game.from_snapshot(snapshot,fixture.registry())


if __name__=='__main__':unittest.main()
