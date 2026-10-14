"""Source-independent tribal Rush through existing player effects and unions.

BOT_238 is an isolated battlecry seam. Its changing five hero powers are not
adapted here: the existing fixture power makes that limitation explicit.
"""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (AddPlayerEffect, Attack, AwakenMinion, CardClass, CardDefinition,
    CardType, EndTurn, Game, IllegalAction, Keyword, MakeDormant, PlayerEffectSpec,
    PlayerKeywordAuraSpec, PlayerSetup, PlayCard, Rarity, RemovePlayerEffect, Scenario,
    SelectChoice, SnapshotError, TribeChangeSpec, ChangeMinionTribes, UnsupportedDefinitionError, ResolutionError, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, RequestChoice, ReplaceHero, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

BOOM='BOT_238'
AURA=PlayerKeywordAuraSpec(Keyword.RUSH,('mech',))
SPEC=PlayerEffectSpec('boom.mech.rush',BOOM,keyword_auras=(AURA,))
FIXTURE=Path(__file__).resolve().parents[1]/'data/support/player-keyword-aura-basics.json'
PIN='cf9ddf50c2cab9c631dde1479f1c6d12b999060ba22449b617aa792b27b8f968'


def evidence():
    raw=json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw)!=PIN:raise ValueError('Player keyword aura full raw changed')
    row=raw['records'][0]
    if row['id']!=BOOM or canonical_digest(row['data'])!=row['data_sha256']:
        raise ValueError('Player keyword aura original row changed')
    return row['data']


def registry(scripts=()):
    r=opening_registry();row=evidence()
    r.register_player_effect(SPEC)
    r.register_behavior('boom.rush',lambda c:(AddPlayerEffect(c.player_id,SPEC.id,c.source_id),))
    r.register_card(CardDefinition(BOOM,row['name'],CardType.HERO,cost=row['cost'],health=row['health'],
        hero_card=True,hero_armor=row['tags']['ARMOR'],initial_hero_power='warrior.power',battlecry='boom.rush',
        metadata=metadata(CardClass.WARRIOR,rarity=Rarity.LEGENDARY)))
    for cid,tribes,intrinsic in (('mech',('mech',),()),('plain',(),()),('mixed',('mech','undead'),()),
            ('all',('all',),()),('intrinsic',('mech',),(Keyword.RUSH,)),('unknown',None,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=3,health=8,keywords=intrinsic,
            metadata=metadata(tribes=tribes)))
    r.register_card(CardDefinition('hidden.X','Hidden X',CardType.MINION,attack=1,health=1,metadata=metadata()))
    actions=(
        ('install',lambda c:(AddPlayerEffect(c.player_id,SPEC.id,c.source_id),),False),
        ('remove',lambda c:(RemovePlayerEffect(c.player_id,c.state.players[c.player_id].player_effects[0].id),),False),
        ('silence',lambda c:(Silence(c.target_id),),True),
        ('kill',lambda c:(Destroy(c.target_id,c.source_id),),True),
        ('steal',lambda c:(ChangeControl(c.target_id,c.player_id),),True),
        ('give',lambda c:(ChangeControl(c.target_id,3-c.player_id),),True),
        ('to.plain',lambda c:(Transform(c.target_id,'plain'),),True),
        ('to.mech',lambda c:(Transform(c.target_id,'mech'),),True),
        ('return',lambda c:(ReturnToHand(c.target_id),),True),
        ('copy.current',lambda c:(CopyMinion(c.target_id,c.player_id),),True),
        ('copy.base',lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),True),
        ('copy.enemy',lambda c:(CopyMinion(c.target_id,3-c.player_id),),True),
        ('tribe.remove',lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('remove',('mech',))),),True),
        ('tribe.add',lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('add',('mech',))),),True),
        ('sleep',lambda c:(MakeDormant(c.target_id,None,c.source_id),),True),
        ('summon',lambda c:(Summon(c.player_id,'mech'),),False),
        ('replace.hero',lambda c:(ReplaceHero(c.player_id,'mage.hero'),),False),
        ('copy.hand',lambda c:(CopyCard(CardReference.capture(next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id=='mech')),c.player_id,Zone.HAND),),False),
        *scripts)
    for name,callback,targeted in actions:
        r.register_behavior(name,callback)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=targeted,metadata=metadata()))
    return r


def rehash(snapshot):
    snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()
        if k not in ('schema_version','events','events_hash','state_hash')})
    return snapshot


class PlayerKeywordAuraTests(unittest.TestCase):
    def setUp(self):self.scripts=[]
    def game(self,hand=('install',),board=('mech','plain'),enemy=('mech',),enemy_hand=(),deck=('plain',)*6):
        return Game.from_scenario(Scenario((PlayerSetup('warrior.hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('mage.hero',hand=enemy_hand,board=enemy,deck=('plain',)*6,mana=10,max_mana=10)),seed=43),registry(self.scripts))
    def play(self,g,cid,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target));return eid
    def rush(self,g,eid,expected=True):
        self.assertEqual(Keyword.RUSH in g.state.entities[eid].keywords,expected)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));restored=Game.from_snapshot(s,registry(self.scripts))
        self.assertEqual(restored.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(self.scripts)).snapshot(),s);return restored
    def choose(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)))

    def test_complete_original_raw_and_isolated_battlecry_declared(self):
        row=evidence();raw=json.loads((FIXTURE.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))
        self.assertEqual(row,next(x for x in raw if x['id']==BOOM))
        self.assertEqual((row['dbf_id'],row['type'],row['cost'],row['tags']['RARITY'],row['tags']['CLASS']),(48146,'HERO',7,5,10))
        r=registry();self.assertEqual(r.card(BOOM).battlecry,'boom.rush')
        self.assertEqual(r.card(BOOM).initial_hero_power,'warrior.power')
        self.assertEqual(r.player_effect(SPEC.id).keyword_auras,(AURA,))

    def test_real_hero_battlecry_installs_source_independent_mech_rush(self):
        g=self.game((BOOM,));mech,plain=g.state.players[1].board;source=self.play(g,BOOM)
        self.rush(g,mech);self.rush(g,plain,False);self.rush(g,g.state.players[2].board[0],False)
        self.assertEqual((g.state.players[1].hero_id,g.state.players[1].mana,g.state.entities[source].armor),(source,3,7))
        self.assertEqual(g.state.players[1].player_effects[0].source_id,source);self.portable(g)

    def test_source_replacement_and_turns_do_not_remove_whole_game_effect(self):
        g=self.game((BOOM,'replace.hero'));source=self.play(g,BOOM);self.play(g,'replace.hero')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.rush(g,g.state.players[1].board[0]);self.portable(g)

    def test_new_summon_has_rush_and_ordinary_enemy_minion_attack(self):
        g=self.game(('install','summon'));self.play(g,'install');self.play(g,'summon');eid=g.state.players[1].board[-1]
        enemy=g.state.players[2].board[0];hero=g.state.players[2].hero_id;self.rush(g,eid)
        self.assertIn(Attack(1,eid,enemy),g.legal_actions());self.assertNotIn(Attack(1,eid,hero),g.legal_actions())
        with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,hero))
        g.apply(Attack(1,eid,enemy));self.assertEqual(g.state.entities[eid].attacks_this_turn,1);self.portable(g)

    def test_new_hand_play_gains_only_on_board_and_does_not_reset_spent_attack(self):
        g=self.game(('install','mech'));eid=g.state.players[1].hand[-1];self.play(g,'install');self.rush(g,eid,False)
        self.play(g,'mech');enemy=g.state.players[2].board[0];g.apply(Attack(1,eid,enemy))
        self.rush(g,eid);self.assertFalse(any(isinstance(a,Attack) and a.attacker_id==eid for a in g.legal_actions()));self.portable(g)

    def test_recipient_silence_keeps_external_contribution(self):
        g=self.game(('install','silence'));eid=g.state.players[1].board[0];self.play(g,'install');self.play(g,'silence',eid)
        self.rush(g,eid);self.assertFalse(any(a.keyword==Keyword.RUSH for a in g.state.entities[eid].abilities));self.portable(g)

    def test_duplicate_instances_union_then_remove_without_erasing_other_source(self):
        g=self.game(('install','install','remove','remove'));eid=g.state.players[1].board[0]
        self.play(g,'install');self.play(g,'install');self.assertEqual(len(g.state.players[1].player_effects),2)
        self.play(g,'remove');self.rush(g,eid);self.play(g,'remove');self.rush(g,eid,False);self.portable(g)

    def test_removal_preserves_intrinsic_rush(self):
        g=self.game(('install','remove'),board=('intrinsic',));eid=g.state.players[1].board[0]
        self.play(g,'install');self.play(g,'remove');self.rush(g,eid);self.assertEqual(g.state.entities[eid].aura_keywords,set());self.portable(g)

    def test_current_tribe_add_remove_and_silence_use_shared_identity(self):
        g=self.game(('install','tribe.remove','silence','tribe.add'),board=('mech','plain'));mech,plain=g.state.players[1].board
        self.play(g,'install');self.play(g,'tribe.remove',mech);self.rush(g,mech,False)
        self.play(g,'silence',mech);self.rush(g,mech);self.play(g,'tribe.add',plain);self.rush(g,plain);self.portable(g)

    def test_multi_tribe_and_all_with_explicit_exclusion(self):
        g=self.game(('install','tribe.remove'),board=('mixed','all'));self.play(g,'install')
        mixed,all_id=g.state.players[1].board;self.rush(g,mixed);self.rush(g,all_id)
        self.play(g,'tribe.remove',all_id);self.rush(g,all_id,False);self.rush(g,mixed);self.portable(g)

    def test_transform_recipient_recomputes_current_face(self):
        g=self.game(('install','to.plain','to.mech'));eid=g.state.players[1].board[0];self.play(g,'install')
        self.play(g,'to.plain',eid);self.rush(g,eid,False);self.play(g,'to.mech',eid);self.rush(g,eid);self.portable(g)

    def test_control_moves_recipient_between_player_scopes(self):
        g=self.game(('install','give','steal'));eid=g.state.players[1].board[0];self.play(g,'install')
        self.play(g,'give',eid);self.rush(g,eid,False);self.play(g,'steal',eid);self.rush(g,eid);self.portable(g)

    def test_current_and_base_copies_get_recipient_effect_without_baking_it(self):
        g=self.game(('install','copy.current','copy.base','remove'));eid=g.state.players[1].board[0];self.play(g,'install')
        self.play(g,'copy.current',eid);self.play(g,'copy.base',eid)
        for i in g.state.players[1].board:
            if g.state.entities[i].card_id=='mech':self.rush(g,i)
        self.play(g,'remove')
        for i in g.state.players[1].board:self.rush(g,i,False)
        self.portable(g)

    def test_current_copy_to_other_player_does_not_inherit_player_rush(self):
        g=self.game(('install','copy.enemy'));eid=g.state.players[1].board[0];self.play(g,'install');self.play(g,'copy.enemy',eid)
        self.rush(g,g.state.players[2].board[-1],False);self.portable(g)

    def test_return_and_stored_copy_clear_board_contribution_and_replay_reapplies(self):
        g=self.game(('install','return','copy.hand'));eid=g.state.players[1].board[0];self.play(g,'install');self.play(g,'return',eid)
        self.rush(g,eid,False);self.play(g,'copy.hand');copied=g.state.players[1].hand[-1];self.rush(g,copied,False)
        self.play(g,'mech');self.rush(g,eid);self.rush(g,copied,False)
        self.play(g,'mech');self.rush(g,copied);self.portable(g)

    def test_dormancy_and_wake_reuse_active_board_scope(self):
        self.scripts.append(('wake',lambda c:(AwakenMinion(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='mech')),),False))
        g=self.game(('install','sleep','wake'));eid=g.state.players[1].board[0];self.play(g,'install');self.play(g,'sleep',eid)
        self.rush(g,eid,False);self.play(g,'wake');self.rush(g,eid);self.portable(g)

    def test_death_clears_dead_recipient_without_removing_player_effect(self):
        g=self.game(('install','kill','summon'));eid=g.state.players[1].board[0];self.play(g,'install');self.play(g,'kill',eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.rush(g,eid,False)
        self.play(g,'summon');self.rush(g,g.state.players[1].board[-1]);self.assertEqual(len(g.state.players[1].player_effects),1);self.portable(g)

    def test_install_wait_restore_preserves_player_effect_and_resumes_summon_once(self):
        self.scripts.append(('wait',lambda c:(AddPlayerEffect(c.player_id,SPEC.id,c.source_id),
            RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),Summon(c.player_id,'mech')),False))
        g=self.game(('wait',));self.play(g,'wait');self.assertIsNotNone(g.state.pending_choice);self.rush(g,g.state.players[1].board[0])
        restored=self.portable(g);self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(len(g.state.players[1].player_effects),1);self.assertEqual(len(g.state.players[1].board),3);self.portable(g)

    def test_late_error_rolls_back_player_effect_keywords_and_rng(self):
        self.scripts.append(('fault',lambda c:(AddPlayerEffect(c.player_id,SPEC.id,c.source_id),AddToHand(c.player_id,'missing')),False))
        g=self.game(('fault',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition'):self.play(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_unknown_current_tribes_error_instead_of_silently_dropping_target(self):
        g=self.game(board=('unknown',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unknown current tribe'):self.play(g,'install')
        self.assertEqual(g.snapshot(),before)

    def test_players_see_public_effect_and_board_keywords_without_private_sources(self):
        g=self.game(enemy_hand=('hidden.X',));self.play(g,'install');before=g.snapshot()
        for viewer in (1,2):
            view=g.observe(viewer);public=view['players'][0]['player_effects'][0]
            self.assertEqual(set(public),{'effect_key','card_id','effect_kind','remaining_turns'})
            self.assertEqual(public['card_id'],BOOM)
            self.assertIn('rush',view['players'][0]['board'][0]['keywords'])
            g.for_player(viewer).legal_actions()
        self.assertNotIn('hidden.X',json.dumps(g.observe(1)));self.assertEqual(g.snapshot(),before)

    def test_rehashed_stale_derived_rush_and_foreign_registry_are_rejected(self):
        g=self.game();self.play(g,'install');s=json.loads(json.dumps(g.snapshot()));eid=g.state.players[1].board[0]
        s['state']['entities'][str(eid)]['aura_keywords']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(s),registry())
        r=registry();r._player_effects[SPEC.id]=replace(SPEC,keyword_auras=(PlayerKeywordAuraSpec(Keyword.RUSH,('beast',)),))
        with self.assertRaises(SnapshotError):Game.from_snapshot(g.snapshot(),r)

    def test_strict_declaration_scope_and_payload_shapes(self):
        for keyword,tribes in (('rush',('mech',)),(Keyword.CHARGE,('mech',)),(Keyword.RUSH,()),(Keyword.RUSH,['mech']),
                (Keyword.RUSH,('mech','mech')),(Keyword.RUSH,(1,))):
            with self.subTest(keyword=keyword,tribes=tribes),self.assertRaises((ValueError,TypeError)):PlayerKeywordAuraSpec(keyword,tribes)
        for values in ([AURA],(object(),)):
            with self.assertRaises(ValueError):replace(SPEC,keyword_auras=values)
        with self.assertRaises(ValueError):replace(SPEC,kind='objective',duration=1,tick_event='turn_ended')
        self.assertEqual(PlayerEffectSpec('plain','mech').keyword_auras,())

    def test_current_protocol_and_previous_schema_explicitly_rejected(self):
        g=self.game();s=g.snapshot();self.assertEqual(s['schema_version'],265)
        self.assertEqual(g.ruleset.id,'prototype-v302');self.assertEqual(g.mechanics.signature['version'],CORE_EFFECTS_VERSION)
        s['schema_version']=191
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_registry_freeze_rejects_unknown_physical_display_card(self):
        r=registry();r.register_player_effect(PlayerEffectSpec('bad','missing',keyword_auras=(AURA,)))
        with self.assertRaises(UnsupportedDefinitionError):r.freeze()
