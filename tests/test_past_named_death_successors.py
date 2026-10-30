"""Actual named successors through paid actions and existing public lifecycles."""
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_named_death_successors as native
from hs_sim.engine import Attack,EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,Destroy,InvokeBehavior,RandomDamage,
    RequestChoice,Silence,Summon,TriggerDeathrattles)
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,DeathrattleRepeatSpec,Keyword,
    SummonQuantitySpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format

SNIP,COOKIE,EXECUTUS,ALAR=native.ROOTS
MICRO,LADLE,RAGNAROS,POWER,ASHES=native.DEPENDENCIES
P='k715.'
A,MECH,QUANTITY,REPEAT,SPELL_DAMAGE=(P+x for x in ('plain','mech','quantity','repeat','spell_damage'))
KILL,EARLY,HUSH,CONTROL,HURT,BUFF,SPAWN=(P+x for x in ('kill','early','hush','control','hurt','buff','spawn'))
WAIT_SUMMON,WAIT_WEAPON,WAIT_HERO,WAIT_POWER,WAIT_DAMAGE=(P+x for x in ('wait_summon','wait_weapon','wait_hero','wait_power','wait_damage'))
FAIL=P+'fail'


@lru_cache(None)
def fixture(role='writer',real_host=False):
    h=build_cn37_local_pool_format() if real_host else None
    r=h.registry if h else defaults()
    if not real_host:native.register_past_named_death_successors(r)
    meta=metadata(collectible=False)
    for cid,extra in ((A,{}),(MECH,dict(metadata=metadata(collectible=False,tribes=('mech',)))),
            (QUANTITY,dict(summon_quantities=(SummonQuantitySpec(),))),
            (REPEAT,dict(deathrattle_repeats=(DeathrattleRepeatSpec(2),))),
            (SPELL_DAMAGE,dict(spell_damage=5))):
        fields=dict(metadata=meta);fields.update(extra)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=3 if cid==MECH else 30,**fields))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),EARLY:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),CONTROL:lambda c:(ChangeControl(c.target_id,2),),
        HURT:lambda c:(Damage(c.state.players[1].hero_id,10,c.source_id,DamageKind.EFFECT),),
        BUFF:lambda c:(Buff(c.target_id,4,4,c.source_id),),
        SPAWN:lambda c:(Summon(c.player_id,SNIP),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            targeting=TargetSpec() if cid in (KILL,EARLY,HUSH,CONTROL,BUFF) else None))
    def fail(c):raise ResolutionError('K715 deliberate accepted continuation failure')
    r.register_behavior(FAIL,fail)
    events={WAIT_SUMMON:'minion_summoned',WAIT_WEAPON:'weapon_equipped',WAIT_HERO:'hero_replaced',
        WAIT_POWER:'hero_power_replaced',WAIT_DAMAGE:'damage_dealt'}
    def wait(c):
        target=c.state.entities.get(c.event.target_id);source=c.state.entities.get(c.event.source_id)
        if c.source.card_id==WAIT_SUMMON:
            if target is None or target.card_id not in (MICRO,ASHES):return ()
        elif c.source.card_id==WAIT_WEAPON:
            if target is None or target.card_id!=LADLE:return ()
        elif c.source.card_id==WAIT_HERO:
            if target is None or target.card_id!=RAGNAROS:return ()
        elif c.source.card_id==WAIT_POWER:
            if target is None or target.card_id!=POWER:return ()
        elif source is None or source.card_id!=POWER:return ()
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after RNG',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        parent=next((i for i in c.state.players[1].board if c.state.entities[i].card_id in native.ROOTS),None)
        if parent is not None:options+=(ChoiceOption('control','Transfer accepted source',(ChangeControl(parent,2),)),)
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(P+'wait',wait)
    for cid,event in events.items():r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,metadata=meta,triggers=(TriggerSpec(event,P+'wait'),)))
    r.validate();return r,None if h is None else h.context


class NamedDeathSuccessorTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),weapon=None,armor=0,real_host=False):
        self.mode='host' if real_host else 'small';r,context=fixture('writer',real_host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*12,
            mana=40,max_mana=40,mana_cap=40,armor=armor,weapon_card_id=weapon,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',board=enemy,deck=(A,)*12,mana=40,max_mana=40,mana_cap=40,
                hero_power_card_id='HERO_08bp')),seed=715,generation_context=context),r)
    def units(self,g,cid,p=1):return [g.state.entities[i]for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def face(self,g,cid,p=1):return next(e for e in self.units(g,cid,p))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def power(self,g,p=1,target=None):g.apply(UseHeroPower(p,g.state.players[p].hero_power_id,target))
    def play_at(self,g,cid,position):
        eid=self.entity(g,cid).id;g.apply(PlayCard(1,eid,position=position));return eid
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:n+=1;self.assertLess(n,30);self.choose(g)
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_nine_physical_faces_and_evidence_roles(self):
        d=native.load_batch();r,_=fixture()
        self.assertEqual(len(d['official_observations']),20);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertTrue(all(cid in r.cards for cid in (*native.ROOTS,*native.DEPENDENCIES)))
        self.assertTrue(all(cid not in r.cards for cid in native.EVIDENCE))
        self.assertEqual(r.card(RAGNAROS).initial_hero_power,POWER)
        self.assertEqual((r.card(ASHES).attack,r.card(ASHES).health),(0,3))
        self.assertTrue(all(not r.card(cid).metadata.collectible for cid in native.DEPENDENCIES))

    def test_all_four_paid_roots_create_exact_successors_once(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,KILL));eid=self.play(g,cid);self.play(g,KILL,eid)
                self.assertEqual(g.state.players[1].mana,40-g.registry.card(cid).cost)
                if cid==SNIP:self.assertEqual(len(self.units(g,MICRO)),2)
                elif cid==COOKIE:self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,LADLE)
                elif cid==EXECUTUS:self.assertEqual((self.hero(g).card_id,self.hero(g).health),(RAGNAROS,8))
                else:self.assertEqual((self.face(g,ASHES).attack,self.face(g,ASHES).health),(0,3))

    def test_Microbot_natural_group_occupies_original_death_slot_in_order(self):
        g=self.game((KILL,),board=(A,SNIP,MECH));eid=self.face(g,SNIP).id;self.play(g,KILL,eid)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[A,MICRO,MICRO,MECH])
        self.assertEqual(len(g.state.ordered_group_history),1);self.assertEqual(len(g.state.card_summon_history),2)

    def test_real_magnetic_play_gives_host_deathrattle_and_one_base_Echo_copy(self):
        g=self.game((SNIP,KILL),board=(MECH,));host=self.face(g,MECH).id;material=self.play_at(g,SNIP,0)
        self.assertEqual(g.state.players[1].board,[host]);self.assertEqual((g.state.entities[host].attack,g.state.entities[host].health),(3,6))
        self.assertEqual(g.state.entities[material].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.magnetic_history),1)
        echo=self.entity(g,SNIP);self.assertEqual((echo.attack,echo.health,echo.cost),(2,3,3));self.assertIsNotNone(echo.hand_lifetime)
        self.play(g,KILL,host);self.assertEqual(len(self.units(g,MICRO)),2);self.portable(g)

    def test_full_board_still_accepts_real_magnetic_without_eighth_body(self):
        g=self.game((SNIP,),board=(MECH,)+(A,)*6);host=self.face(g,MECH).id;self.play_at(g,SNIP,0)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.state.players[1].board[0],host)
        self.assertEqual(len([i for i in g.state.players[1].hand if g.state.entities[i].card_id==SNIP]),1)

    def test_real_Echo_can_be_played_again_and_only_unused_copy_expires(self):
        g=self.game((SNIP,));self.play(g,SNIP);first=self.entity(g,SNIP).id;self.play(g,SNIP);unused=self.entity(g,SNIP).id
        self.assertEqual(len(self.units(g,SNIP)),2);self.assertEqual(g.state.players[1].mana,34)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[first].zone,Zone.BOARD)
        self.assertEqual(g.state.entities[unused].zone,Zone.GRAVEYARD);self.assertFalse(g.state.discard_history);self.portable(g)

    def test_direct_Snip_summon_does_not_create_Echo_or_magnetic_commit(self):
        g=self.game((SPAWN,));self.play(g,SPAWN);self.assertEqual(len(self.units(g,SNIP)),1)
        self.assertEqual(g.state.players[1].hand,[]);self.assertEqual(g.state.magnetic_history,[])

    def test_early_and_repeat_deathrattles_keep_two_original_occurrences_each(self):
        g=self.game((SNIP,EARLY,KILL));eid=self.play(g,SNIP);self.play(g,EARLY,eid);self.play(g,KILL,eid)
        self.assertEqual(len(self.units(g,MICRO)),4)
        g=self.game((SNIP,KILL),board=(REPEAT,));eid=self.play(g,SNIP);self.play(g,KILL,eid)
        self.assertEqual(len(self.units(g,MICRO)),4);self.assertEqual(len(g.state.ordered_group_history),2)

    def test_original_child_quantities_and_capacity_are_shared(self):
        g=self.game((SNIP,KILL),board=(QUANTITY,));eid=self.play(g,SNIP);self.play(g,KILL,eid)
        self.assertEqual(len(self.units(g,MICRO)),4)
        g=self.game((EARLY,),board=(SNIP,)+(A,)*6);rng=g.snapshot()['rng_state'];self.play(g,EARLY,self.face(g,SNIP).id)
        self.assertEqual(self.units(g,MICRO),[]);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_Microbot_wait_restores_complete_group_and_failed_choice(self):
        g=self.game((SNIP,KILL),board=(WAIT_SUMMON,));eid=self.play(g,SNIP);self.play(g,KILL,eid)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(len(self.units(g,MICRO)),2);self.portable(g)

    def test_accepted_Microbot_group_keeps_recipient_when_early_source_changes_control(self):
        g=self.game((SNIP,EARLY),board=(WAIT_SUMMON,));eid=self.play(g,SNIP);self.play(g,EARLY,eid)
        self.choose(g,'control');self.finish(g);self.assertEqual(g.state.entities[eid].controller,2)
        self.assertEqual(len(self.units(g,MICRO)),2);self.assertEqual(self.units(g,MICRO,2),[]);self.portable(g)

    def test_Cookie_root_combat_uses_actual_printed_Lifesteal(self):
        g=self.game((HURT,),board=(COOKIE,));self.play(g,HURT)
        g.apply(Attack(1,self.face(g,COOKIE).id,g.state.players[2].hero_id));self.assertEqual(self.hero(g).health,22)

    def test_actual_Ladle_equipment_attacks_wears_and_heals_actual_damage(self):
        g=self.game((COOKIE,KILL,HURT));eid=self.play(g,COOKIE);self.play(g,KILL,eid);self.play(g,HURT)
        wid=g.state.players[1].weapon_id;g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(self.hero(g).health,22);self.assertEqual(g.state.entities[wid].durability,2);self.portable(g)

    def test_Ladle_replaces_old_weapon_and_restores_equipment_notification(self):
        g=self.game((COOKIE,KILL),board=(WAIT_WEAPON,),weapon='CS2_082');old=g.state.players[1].weapon_id
        eid=self.play(g,COOKIE);self.play(g,KILL,eid);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,LADLE);self.portable(g)

    def test_Executus_installs_actual_eight_health_hero_and_normal_power_with_old_armor(self):
        g=self.game((EXECUTUS,KILL),armor=7);old=self.hero(g).id;eid=self.play(g,EXECUTUS);self.play(g,KILL,eid)
        self.assertEqual((self.hero(g).card_id,self.hero(g).base_health,self.hero(g).health,self.hero(g).armor),(RAGNAROS,8,8,7))
        self.assertNotEqual(self.hero(g).id,old);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,POWER);self.portable(g)

    def test_Ragnaros_normal_power_is_one_actual_eight_damage_power_not_a_spell(self):
        g=self.game((EXECUTUS,KILL),board=(SPELL_DAMAGE,));eid=self.play(g,EXECUTUS);self.play(g,KILL,eid)
        before=g.state.players[1].mana;casts=g.state.cast_history;self.power(g);self.assertEqual(self.hero(g,2).health,22)
        self.assertEqual(g.state.players[1].mana,before-2);self.assertEqual(g.state.cast_history,casts);self.portable(g)

    def test_replacing_used_Mage_power_installs_fresh_normal_Ragnaros_use(self):
        g=self.game((EXECUTUS,KILL));self.power(g,target=g.state.players[2].hero_id)
        eid=self.play(g,EXECUTUS);self.play(g,KILL,eid);self.power(g);self.assertEqual(self.hero(g,2).health,21)

    def test_hero_replacement_wait_continues_pending_normal_power_install_once(self):
        g=self.game((EXECUTUS,KILL),board=(WAIT_HERO,));eid=self.play(g,EXECUTUS);self.play(g,KILL,eid)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,POWER);self.portable(g)

    def test_power_replacement_wait_restores_actual_installed_power(self):
        g=self.game((EXECUTUS,KILL),board=(WAIT_POWER,));eid=self.play(g,EXECUTUS);self.play(g,KILL,eid)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.finish(g);self.power(g)
        self.assertEqual(self.hero(g,2).health,22);self.portable(g)

    def test_actual_power_damage_wait_restores_original_random_hit_without_reselection(self):
        g=self.game((EXECUTUS,KILL),board=(WAIT_DAMAGE,));eid=self.play(g,EXECUTUS);self.play(g,KILL,eid);self.power(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.hero(g,2).health,22);self.portable(g)

    def test_Alar_Ashes_transform_on_next_owner_start_and_can_repeat_actual_cycle(self):
        g=self.game((ALAR,KILL,KILL));eid=self.play(g,ALAR);self.play(g,KILL,eid);ashes=self.face(g,ASHES).id
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[ashes].card_id,ASHES)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[ashes].card_id,ALAR)
        self.assertEqual((g.state.entities[ashes].attack,g.state.entities[ashes].health),(7,3))
        self.play(g,KILL,ashes);self.assertEqual(len(self.units(g,ASHES)),1);self.portable(g)

    def test_Ashes_use_current_controller_owner_turn_after_transfer(self):
        g=self.game((ALAR,KILL,CONTROL));eid=self.play(g,ALAR);self.play(g,KILL,eid);ash=self.face(g,ASHES).id
        self.play(g,CONTROL,ash);g.apply(EndTurn(1));self.assertEqual(g.state.entities[ash].card_id,ALAR)
        self.assertEqual(g.state.entities[ash].controller,2);self.portable(g)

    def test_Ashes_silence_blocks_while_ordinary_Transform_discards_old_buffs(self):
        g=self.game((HUSH,),board=(ASHES,));ash=self.face(g,ASHES).id;self.play(g,HUSH,ash)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.entities[ash].card_id,ASHES)
        g=self.game((BUFF,),board=(ASHES,));ash=self.face(g,ASHES).id;self.play(g,BUFF,ash)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual((g.state.entities[ash].attack,g.state.entities[ash].health),(7,3))

    def test_Ashes_summon_notification_wait_restores_then_actual_owner_transform(self):
        g=self.game((ALAR,KILL),board=(WAIT_SUMMON,));eid=self.play(g,ALAR);self.play(g,KILL,eid)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        ash=self.face(g,ASHES).id;g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.entities[ash].card_id,ALAR);self.portable(g)

    def test_all_four_silenced_roots_have_no_named_deathrattle_payload(self):
        for cid in native.ROOTS:
            g=self.game((cid,HUSH,KILL));eid=self.play(g,cid);self.play(g,HUSH,eid);self.play(g,KILL,eid)
            self.assertEqual(self.units(g,MICRO)+self.units(g,ASHES),[])
            self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(self.hero(g).card_id,'HERO_08')

    def test_all_four_deathrattles_follow_actual_new_controller(self):
        for cid in native.ROOTS:
            g=self.game((cid,CONTROL,KILL));eid=self.play(g,cid);self.play(g,CONTROL,eid);self.play(g,KILL,eid)
            if cid==SNIP:self.assertEqual(len(self.units(g,MICRO,2)),2)
            elif cid==COOKIE:self.assertEqual(g.state.entities[g.state.players[2].weapon_id].card_id,LADLE)
            elif cid==EXECUTUS:self.assertEqual(self.hero(g,2).card_id,RAGNAROS)
            else:self.assertEqual(len(self.units(g,ASHES,2)),1)

    def test_generated_minion_weapon_and_Ashes_keep_their_normal_paid_entries(self):
        for cid in (MICRO,LADLE,ASHES):
            g=self.game((cid,));self.play(g,cid);self.assertEqual(g.state.players[1].mana,40-g.registry.card(cid).cost)

    def test_actual_host_four_paid_native_roots_and_all_named_successors(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,KILL),real_host=True);eid=self.play(g,cid);self.play(g,KILL,eid)
                if cid==SNIP:self.assertEqual(len(self.units(g,MICRO)),2)
                elif cid==COOKIE:self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,LADLE)
                elif cid==EXECUTUS:self.power(g);self.assertEqual(self.hero(g,2).health,22)
                else:g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(len(self.units(g,ALAR)),1)
        self.portable(g)


if __name__=='__main__':unittest.main()
