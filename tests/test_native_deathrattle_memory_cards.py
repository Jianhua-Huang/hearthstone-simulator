"""Native growth and exact physical draw linkage through real shared lifecycle paths."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from copy import deepcopy
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.native_deathrattle_memory_cards import load_batch
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Ruleset,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone
from hs_sim.engine.deathrattle_memory import DrawForDeathrattle
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,CopyMinion,Destroy,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CastWhenDrawnSpec,DeathrattleMemory,NativeDeathrattleSpec,RememberedDraw
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CapturedCardCopyMaterial,CopyCard
from hs_sim.engine.copy_materials import CopyEntryMaterial,validate_captured_card_copy,validate_scope
from hs_sim.targets import canonical_digest

EGG='CATA_210';WHELP='CATA_210t';PLAT='TLC_603';YETI='CORE_CS2_182';MIRROR='DINO_407'


def registry():
    r=build_registry()
    def redraw(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==PLAT)
        return(DrawForDeathrattle(c.player_id,MinionReference.capture(source),tuple(a.id for a in active_abilities(source,'deathrattle')if a.deathrattle_memory is not None)),)
    def listener(c,kind):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id!=PLAT or source.zone!=Zone.BOARD:return ()
        if kind=='kill':return(Destroy(source.id,c.source_id),)
        if kind=='copy':
            links=tuple(x for a in source.abilities if a.deathrattle_memory is not None for x in a.deathrattle_memory.draws)
            if not any(x.draw_id==dict(c.event.data)['draw_id']for x in links):
                raise AssertionError('Captured draw-notification state preceded its original Deathrattle linkage')
            return(CopyCard(MinionReference.capture(source),c.player_id,mode='current',source_id=c.source_id),)
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),ChoiceOption('bad','Fail',(InvokeBehavior('k62.fail',c.source_id,c.player_id),))),source_id=c.source_id),)
    bodies=dict(empty=lambda c:(),kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        bounce=lambda c:(ReturnToHand(c.target_id),),change=lambda c:(Transform(c.target_id,YETI),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),),base_copy=lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        give=lambda c:(ChangeControl(c.target_id,3-c.player_id),),redraw=redraw,
        fill_redraw=lambda c:(AddToHand(c.player_id,YETI,c.source_id),InvokeBehavior('k62.redraw',c.source_id,c.player_id)),
        fail=lambda c:(AddToHand(c.player_id,'k62.missing',c.source_id),))
    for name,body in bodies.items():r.register_behavior('k62.'+name,body)
    for name in ('kill','silence','bounce','change','copy','base_copy','give','redraw','fill_redraw'):
        r.register_card(CardDefinition('k62.'+name,name,CardType.SPELL,on_play='k62.'+name,requires_target=name not in ('redraw','fill_redraw')))
    for kind in ('kill','copy','choice'):
        r.register_behavior('k62.listener.'+kind,lambda c,k=kind:listener(c,k))
        r.register_card(CardDefinition('k62.listener.'+kind,kind,CardType.MINION,health=4,triggers=(TriggerSpec('card_drawn','k62.listener.'+kind),)))
    r.register_card(CardDefinition('k62.cwd','Casts-when-drawn fixture',CardType.SPELL,on_play='k62.empty',
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=False)))
    return r


class NativeDeathrattleMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),deck=(YETI,)*8,enemy_hand=(),enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30)),seed=1062),self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        eid=self.entity(g,cid,p,zone='hand').id;g.apply(PlayCard(p,eid,target));return eid
    def mem(self,g,eid):return next(a.deathrattle_memory for a in g.state.entities[eid].abilities if a.deathrattle_memory is not None)
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(s,registry()).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
    def test_complete_three_faces_and_original_two_one_token(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['cards']],[EGG,PLAT]);self.assertEqual(d['dependencies'][0]['record']['id'],WHELP)
        for x in d['cards']+d['dependencies']:self.assertEqual(canonical_digest(x['record']),x['record_sha256'])
        self.assertEqual((self.r.card(WHELP).attack,self.r.card(WHELP).health),(2,1))
    def test_default_fingerprint_unchanged(self):
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_egg_initial_death_summons_complete_two_one(self):
        g=self.game((EGG,'k62.kill'));eid=self.play(g,EGG);self.play(g,'k62.kill',eid);e=self.entity(g,WHELP);self.assertEqual((e.attack,e.health),(2,1));self.portable(g)
    def test_growth_changes_deathrattle_not_eggs_body(self):
        g=self.game((EGG,));eid=self.play(g,EGG);self.cycle(g);self.assertEqual(self.mem(g,eid).growth_steps,1);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(0,2));self.portable(g)
    def test_opponent_start_does_not_grow_friendly_egg(self):
        g=self.game((EGG,));eid=self.play(g,EGG);g.apply(EndTurn(1));self.assertEqual(self.mem(g,eid).growth_steps,0)
    def test_two_owner_starts_summon_four_three(self):
        g=self.game((EGG,'k62.kill'));eid=self.play(g,EGG);self.cycle(g);self.cycle(g);self.play(g,'k62.kill',eid);e=self.entity(g,WHELP);self.assertEqual((e.attack,e.health),(4,3));self.portable(g)
    def test_egg_in_hand_does_not_grow(self):
        g=self.game((EGG,));eid=self.entity(g,EGG,zone='hand').id;self.cycle(g);self.assertEqual(self.mem(g,eid).growth_steps,0)
    def test_current_copy_carries_value_and_grows_independently(self):
        g=self.game((EGG,'k62.copy','k62.silence'));eid=self.play(g,EGG);self.cycle(g);self.play(g,'k62.copy',eid);ids=[i for i in g.state.players[1].board if g.state.entities[i].card_id==EGG];other=next(i for i in ids if i!=eid)
        self.assertEqual(self.mem(g,other).growth_steps,1);self.play(g,'k62.silence',eid);self.cycle(g);self.assertEqual(self.mem(g,other).growth_steps,2);self.assertFalse(any(a.deathrattle_memory is not None for a in g.state.entities[eid].abilities));self.portable(g)
    def test_base_copy_starts_fresh(self):
        g=self.game((EGG,'k62.base_copy'));eid=self.play(g,EGG);self.cycle(g);self.play(g,'k62.base_copy',eid);other=next(i for i in g.state.players[1].board if i!=eid);self.assertEqual(self.mem(g,other).growth_steps,0)
    def test_silenced_egg_loses_growth_and_hatching(self):
        g=self.game((EGG,'k62.silence','k62.kill'));eid=self.play(g,EGG);self.cycle(g);self.play(g,'k62.silence',eid);self.play(g,'k62.kill',eid);self.assertFalse(g.state.players[1].board)
    def test_return_to_hand_resets_egg_memory(self):
        g=self.game((EGG,'k62.bounce'));eid=self.play(g,EGG);self.cycle(g);self.play(g,'k62.bounce',eid);self.assertEqual(self.mem(g,eid).growth_steps,0);self.play(g,EGG);self.assertEqual(self.mem(g,eid).growth_steps,0);self.portable(g)
    def test_growth_uses_current_controller_after_transfer(self):
        g=self.game((EGG,'k62.give'));eid=self.play(g,EGG);self.play(g,'k62.give',eid);g.apply(EndTurn(1));self.assertEqual(self.mem(g,eid).growth_steps,1);g.apply(EndTurn(2));self.assertEqual(self.mem(g,eid).growth_steps,1);self.portable(g)
    def test_public_growth_numbers_visible_to_both_players(self):
        g=self.game((EGG,));eid=self.play(g,EGG);self.cycle(g)
        for p in (1,2):
            from hs_sim.engine.information import VIEW_VERSION
            v=g.observe(p);row=next(x for x in v['players'][0]['board']if x['card_id']==EGG);self.assertEqual(v['version'],VIEW_VERSION);self.assertEqual(row['deathrattle_summons'],[dict(card_id=WHELP,attack=3,health=2)])
    def test_silence_removes_public_growth_projection(self):
        g=self.game((EGG,'k62.silence'));eid=self.play(g,EGG);self.play(g,'k62.silence',eid);self.assertNotIn('deathrattle_summons',g.observe(2)['players'][0]['board'][0])
    def test_real_repeated_source_uses_captured_memory_and_original_draws(self):
        for cid in (EGG,PLAT):
            with self.subTest(card=cid):
                g=self.game((cid,'k62.kill'),board=('TIME_064',));eid=self.play(g,cid)
                if cid==PLAT:self.assertEqual(len(self.mem(g,eid).draws),2)
                self.play(g,'k62.kill',eid)
                if cid==EGG:self.assertEqual(sum(g.state.entities[i].card_id==WHELP for i in g.state.players[1].board),2)
                else:self.assertEqual(len(g.state.discard_history),2)
                self.portable(g)
    def test_platysaur_draws_and_discards_exact_original_card(self):
        g=self.game((PLAT,'k62.kill'));eid=self.play(g,PLAT);link=self.mem(g,eid).draws[0];self.play(g,'k62.kill',eid);self.assertEqual(g.state.discard_history[-1].entity_id,link.entity_id);self.portable(g)
    def test_similarly_named_other_hand_card_is_not_discarded(self):
        g=self.game((PLAT,'k62.kill',YETI));other=self.entity(g,YETI,zone='hand').id;eid=self.play(g,PLAT);self.play(g,'k62.kill',eid);self.assertIn(other,g.state.players[1].hand)
    def test_already_played_drawn_card_is_not_discarded(self):
        g=self.game((PLAT,'k62.kill'));eid=self.play(g,PLAT);drawn=self.play(g,YETI);self.play(g,'k62.kill',eid);self.assertEqual(g.state.entities[drawn].zone,Zone.BOARD);self.assertEqual(len(g.state.discard_history),0)
    def test_left_and_returned_card_is_not_rebound(self):
        g=self.game((PLAT,'k62.kill','k62.bounce'));eid=self.play(g,PLAT);drawn=self.play(g,YETI);self.play(g,'k62.bounce',drawn);self.play(g,'k62.kill',eid);self.assertIn(drawn,g.state.players[1].hand);self.assertEqual(len(g.state.discard_history),0);self.portable(g)
    def test_same_hand_stay_face_change_keeps_original_draw_link(self):
        g=self.game((PLAT,'k62.kill'),deck=(MIRROR,)+(YETI,)*5,enemy_hand=(YETI,));eid=self.play(g,PLAT);link=self.mem(g,eid).draws[0];g.apply(EndTurn(1));self.play(g,YETI,p=2);g.apply(EndTurn(2));self.assertEqual(g.state.entities[link.entity_id].card_id,YETI);self.play(g,'k62.kill',eid);self.assertEqual(g.state.discard_history[-1].entity_id,link.entity_id);self.portable(g)
    def test_draw_reaction_killing_platysaur_already_sees_link(self):
        g=self.game((PLAT,),board=('k62.listener.kill',));eid=self.play(g,PLAT);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.discard_history),1);self.portable(g)
    def test_captured_copy_at_draw_notification_already_contains_memory(self):
        g=self.game((PLAT,),board=('k62.listener.copy',));eid=self.play(g,PLAT);copy=self.entity(g,PLAT,zone='hand');self.assertEqual(self.mem(g,copy.id).draws,self.mem(g,eid).draws);self.assertEqual(len(self.mem(g,copy.id).draws),1);self.portable(g)
    def test_copy_retains_old_draw_and_can_record_new_battlecry_draw(self):
        g=self.game((PLAT,'k62.kill','k62.kill'),board=('k62.listener.copy',));eid=self.play(g,PLAT);copy=self.entity(g,PLAT,zone='hand').id;self.play(g,'k62.kill',eid);self.play(g,PLAT);self.assertEqual(len(self.mem(g,copy).draws),2);self.play(g,'k62.kill',copy);self.assertEqual(len(g.state.discard_history),2);self.portable(g)
    def test_current_board_copy_discards_shared_original_once(self):
        g=self.game((PLAT,'k62.copy','k62.kill','k62.kill'));eid=self.play(g,PLAT);self.play(g,'k62.copy',eid);other=next(i for i in g.state.players[1].board if i!=eid);self.play(g,'k62.kill',eid);self.play(g,'k62.kill',other);self.assertEqual(len(g.state.discard_history),1);self.portable(g)
    def test_silence_removes_original_discard_memory(self):
        g=self.game((PLAT,'k62.silence','k62.kill'));eid=self.play(g,PLAT);self.play(g,'k62.silence',eid);self.play(g,'k62.kill',eid);self.assertEqual(len(g.state.discard_history),0)
    def test_transform_removes_discard_body(self):
        g=self.game((PLAT,'k62.change','k62.kill'));eid=self.play(g,PLAT);self.play(g,'k62.change',eid);self.play(g,'k62.kill',eid);self.assertEqual(len(g.state.discard_history),0)
    def test_fatigue_creates_no_hand_link(self):
        g=self.game((PLAT,'k62.kill'),deck=());eid=self.play(g,PLAT);self.assertEqual(self.mem(g,eid).draws,());self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29);self.play(g,'k62.kill',eid);self.assertEqual(len(g.state.discard_history),0)
    def test_cast_when_drawn_is_not_a_hand_link(self):
        g=self.game((PLAT,'k62.kill'),deck=('k62.cwd',));eid=self.play(g,PLAT);self.assertEqual(g.state.draw_history[-1].outcome,'cast');self.assertEqual(self.mem(g,eid).draws,());self.play(g,'k62.kill',eid);self.assertEqual(len(g.state.discard_history),0);self.portable(g)
    def test_burned_draw_is_not_a_hand_link(self):
        g=self.game(('k62.fill_redraw',)+(YETI,)*9,board=(PLAT,));eid=self.entity(g,PLAT).id;self.play(g,'k62.fill_redraw');self.assertEqual(g.state.draw_history[-1].outcome,'burned');self.assertEqual(self.mem(g,eid).draws,());self.portable(g)
    def test_original_draw_owner_is_preserved_after_source_transfer(self):
        g=self.game((PLAT,'k62.give'),enemy_hand=('k62.kill',));eid=self.play(g,PLAT);self.play(g,'k62.give',eid);g.apply(EndTurn(1));self.play(g,'k62.kill',eid,p=2);self.assertEqual(g.state.discard_history[-1].player_id,1);self.portable(g)
    def test_multiple_actual_battlecry_draws_preserve_order(self):
        g=self.game((PLAT,'k62.redraw','k62.kill'));eid=self.play(g,PLAT);self.play(g,'k62.redraw');links=self.mem(g,eid).draws;self.assertEqual(len(links),2);self.play(g,'k62.kill',eid);self.assertEqual([x.entity_id for x in g.state.discard_history],[x.entity_id for x in links]);self.portable(g)
    def test_draw_choice_suspension_contains_original_memory_and_restores(self):
        g=self.game((PLAT,'k62.kill'),board=('k62.listener.choice',));eid=self.play(g,PLAT);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.mem(g,eid).draws),1);self.portable(g);q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,('ok',)));self.play(g,'k62.kill',eid);self.portable(g)
    def test_failed_draw_choice_restores_exact_waiting_state(self):
        g=self.game((PLAT,),board=('k62.listener.choice',));self.play(g,PLAT);before=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('bad',)))
        self.assertEqual(g.snapshot(),before)
    def test_private_draw_link_is_not_exported_to_either_player(self):
        g=self.game((PLAT,));self.play(g,PLAT)
        for p in (1,2):
            row=next(x for x in g.observe(p)['players'][0]['board']if x['card_id']==PLAT);raw=json.dumps(row);self.assertNotIn('deathrattle_memory',raw);self.assertNotIn('hand_entry_id',raw);self.assertNotIn('draw_id',raw);self.assertNotIn('deathrattle_summons',row)
    def test_pure_queries_preserve_all_memory_and_rng(self):
        g=self.game((PLAT,EGG));self.play(g,PLAT);self.play(g,EGG);before=g.snapshot()
        for p in (1,2):g.for_player(p).observe();g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(),before)
    def test_tampered_draw_references_and_profiles_are_rejected(self):
        g=self.game((PLAT,));eid=self.play(g,PLAT);before=g.snapshot()
        for change in [dict(draw_id=999999),dict(hand_entry_id=1),dict(source_id=999999),dict(entity_id=eid)]:
            with self.subTest(change=change):
                bad=deepcopy(before);a=next(a for a in bad['state']['entities'][str(eid)]['abilities']if a['deathrattle_memory']is not None);a['deathrattle_memory']['draws'][0].update(change)
                with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
    def test_memory_cannot_mix_growth_and_draw_payloads(self):
        with self.assertRaises(ValueError):DeathrattleMemory(NativeDeathrattleSpec('draw_link'),growth_steps=1)
        with self.assertRaises(ValueError):DeathrattleMemory(NativeDeathrattleSpec('summon_growth',WHELP,2,1),draws=(RememberedDraw(1,1,1,1),))
    def bad_draw_material(self,material):
        abilities=[]
        for ability in material.local.abilities:
            memory=ability.deathrattle_memory
            if memory is not None:ability=replace(ability,deathrattle_memory=replace(memory,draws=(replace(memory.draws[0],draw_id=999999),)))
            abilities.append(ability)
        return replace(material,local=replace(material.local,abilities=tuple(abilities)))
    def test_frozen_stored_copy_rejects_unknown_remembered_draw(self):
        g=self.game((PLAT,),board=('k62.listener.copy',));self.play(g,PLAT);s=g.state;copy=self.entity(g,PLAT,zone='hand');material=CapturedCardCopyMaterial.capture(s,copy)
        validate_captured_card_copy(s,self.r,material)
        with self.assertRaises(ValueError):validate_captured_card_copy(s,self.r,self.bad_draw_material(material))
    def test_frozen_board_copy_rejects_unknown_remembered_draw(self):
        g=self.game((PLAT,));eid=self.play(g,PLAT);s=g.state;material=CopyEntryMaterial.capture(s,s.entities[eid],'board_copy','current');validate_scope(s,self.r,material)
        with self.assertRaises(ValueError):validate_scope(s,self.r,self.bad_draw_material(material))


if __name__=='__main__':unittest.main()
