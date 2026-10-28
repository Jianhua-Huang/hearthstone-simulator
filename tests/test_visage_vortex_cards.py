"""Real secret combat, complete Vortex forms, original count and portable waits."""
from functools import lru_cache
from random import Random
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import visage_vortex_cards as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SpellSchool
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,ForceAttack,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,Keyword,SummonQuantitySpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.player_spell_count_costs import count_distinct_cast_schools
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.local_pool_format import build_cn37_local_pool_format

VISAGE,INSPIRATION=native.LEAVES;P='k632.'
UNIT,TAUNT,FILL,WATCH,DOUBLE,WEAPON=(P+x for x in ('unit','taunt','fill','watch','double','weapon'))
AUTO,OTHER,BUFF,HURT,FORCE,FAIL=(P+x for x in ('auto','other','buff','hurt','force','fail'))
SCHOOLS=tuple(SpellSchool);SPELLS=tuple(P+x.value for x in SCHOOLS)


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_visage_vortex_cards(r)
    r.register_behavior(P+'noop',lambda c:())
    for school,cid in zip(SCHOOLS,SPELLS):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=P+'noop',spell_school=school,
            metadata=metadata(CardClass.MAGE,tribes=())))
    for cid,attack,health,kw in ((UNIT,3,6,()),(TAUNT,1,10,(Keyword.TAUNT,)),(FILL,0,10,()),(WATCH,0,100,()),(DOUBLE,0,5,())):
        triggers=(TriggerSpec({'reveal':'secret_revealed','random':'random_choice'}.get(mode,'minion_summoned'),P+'watch'),) if cid==WATCH and mode!='normal' else ()
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,keywords=kw,triggers=triggers,
            summon_quantities=(SummonQuantitySpec(),) if cid==DOUBLE else (),metadata=metadata(tribes=())))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=2,durability=3,metadata=metadata(tribes=())))
    def force(c):
        unit=next(c.state.entities[i] for i in c.state.players[3-c.player_id].board if c.state.entities[i].card_id==UNIT)
        return (ForceAttack(unit.id,c.state.players[c.player_id].hero_id),)
    scripts={AUTO:lambda c:(CastSpell(c.player_id,SPELLS[0],c.source_id),CastSpell(c.player_id,SPELLS[0],c.source_id)),
        OTHER:lambda c:(CastSpell(3-c.player_id,SPELLS[-1],c.source_id),),
        BUFF:lambda c:(Buff(c.target_id,2,2,c.source_id),),HURT:lambda c:(Damage(c.target_id,1,c.source_id),),FORCE:force}
    for cid,body in scripts.items():
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))} if cid in (BUFF,HURT) else {}
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=()),**extra))
    def fail(c):raise ResolutionError('K632 deliberate RNG rollback')
    r.register_behavior(FAIL,fail)
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);unit=c.state.entities.get(e.target_id)
        if mode=='reveal':
            if source is None or source.card_id!=VISAGE:return ()
        elif mode=='random':
            if source is None or source.card_id!=INSPIRATION:return ()
        elif unit is None or unit.controller!=c.player_id or unit.card_id not in (*native.VORTICES,UNIT):return ()
        options=[ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),
            ChoiceOption('school','Later new school',(CastSpell(c.player_id,SPELLS[-1],c.source_id),))]
        if unit is not None and unit.kind==CardType.MINION and unit.zone==Zone.BOARD:
            options.append(ChoiceOption('bounce','Return original delivery',(ReturnToHand(unit.id),)))
        if mode=='reveal':
            attacker=next((c.state.entities[i] for i in c.state.players[3-c.player_id].board if c.state.entities[i].card_id==UNIT),None)
            if attacker is not None:options.append(ChoiceOption('kill','Remove original attacker',(Destroy(attacker.id,c.source_id),)))
        return (RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(P+'watch',watch);r.validate();r.freeze();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format().registry


class VisageVortexTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,board=(),enemy=(),other_hand=(),weapon=None,player=1,mode='normal',seed=71):
        self.mode=mode
        setups=[PlayerSetup('mage.hero',hand=hand,board=board,deck=(FILL,)*12,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,weapon_card_id=weapon,deck=(FILL,)*12,mana=40,max_mana=40,mana_cap=40)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=seed),registry(mode))
    def units(self,g,p=1):return [g.state.entities[i] for i in g.state.players[p].board]
    def vortex(self,g,p=1):return [e for e in self.units(g,p) if e.card_id in native.VORTICES]
    def randoms(self,g):return [e for e in g.events if e.kind=='random_choice' and dict(e.data).get('producer')=='effect_branch']
    def arm(self,g,p=1):
        source=self.play(g,VISAGE,player=p);g.apply(EndTurn(p));return source
    def hit(self,g,p=2,target=None):
        attacker=self.entity(g,UNIT,p,'board').id;g.apply(Attack(p,attacker,target or g.state.players[3-p].hero_id));return attacker
    def settle(self,g,key='continue'):
        while g.state.pending_choice is not None:
            g=self.portable(g);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'K632'):self.choose(g,'fail')
            self.assertEqual(saved,g.snapshot());self.choose(g,key)
        return g

    def test_full_ten_rows_four_primary_faces_and_exact_eight_children(self):
        data=native.load_batch();rows={x['record']['id']:x['record'] for x in data['dependencies']}
        for obs in data['official_observations']:
            batch.check_face(rows[obs['card_id']],obs['face'],obs['locale'],data['display_normalizations'].get(obs['card_id']))
        self.assertEqual(tuple(rows),native.DEPENDENCIES);self.assertEqual(data['vortex_weights'],[1]*8)
        self.assertFalse(data['source_scope_bound']);self.assertFalse(data['cn_calibrated'])

    def test_all_tokens_have_exactly_one_real_bonus_and_elemental_metadata(self):
        r=registry()
        for cid,bonus in zip(native.VORTICES,native.BONUSES):
            d=r.card(cid);self.assertEqual((d.cost,d.attack,d.health,d.keywords),(4,4,5,(bonus,)))
            self.assertFalse(d.metadata.collectible);self.assertEqual(d.metadata.tribes,('elemental',))

    def test_secret_real_payment_hidden_zone_and_duplicate_atomicity(self):
        g=self.game((VISAGE,VISAGE),enemy=(UNIT,));source=self.play(g,VISAGE)
        self.assertEqual(g.state.players[1].mana,37);self.assertIn(source,g.state.players[1].secrets)
        saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,VISAGE)
        self.assertEqual(g.snapshot(),saved);self.assertNotIn(VISAGE,str(g.for_player(2).observe()))

    def test_enemy_completed_hero_attack_copies_current_buffs_damage_and_forces_attack(self):
        g=self.game((VISAGE,),enemy=(UNIT,),other_hand=(BUFF,HURT));self.arm(g)
        attacker=self.entity(g,UNIT,2,'board').id;self.play(g,BUFF,attacker,player=2);self.play(g,HURT,attacker,player=2)
        self.hit(g);copied=self.entity(g,UNIT,1,'board')
        self.assertEqual((copied.attack,copied.health,copied.max_health),(5,7,8))
        self.assertEqual((g.state.entities[g.state.players[1].hero_id].health,g.state.entities[g.state.players[2].hero_id].health),(25,25))
        self.assertFalse(g.state.players[1].secrets);self.assertEqual(len(g.state.character_attack_history),2);self.portable(g)

    def test_copied_force_targets_enemy_hero_despite_enemy_taunt(self):
        g=self.game((VISAGE,),enemy=(UNIT,TAUNT));self.arm(g);self.hit(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        self.assertEqual(self.entity(g,TAUNT,2,'board').health,10)

    def test_both_seats_retain_actual_secret_owner(self):
        g=self.game((VISAGE,),enemy=(UNIT,),player=2);self.arm(g,2);self.hit(g,1)
        self.assertEqual(self.entity(g,UNIT,2,'board').attack,3);self.assertFalse(g.state.players[2].secrets)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)

    def test_enemy_attack_on_minion_keeps_secret(self):
        g=self.game((VISAGE,),board=(FILL,),enemy=(UNIT,));self.arm(g)
        self.hit(g,target=self.entity(g,FILL,1,'board').id);self.assertEqual(len(g.state.players[1].secrets),1)
        self.assertFalse(any(e.card_id==UNIT for e in self.units(g)))

    def test_enemy_hero_attack_keeps_secret(self):
        g=self.game((VISAGE,),weapon=WEAPON);self.arm(g)
        g.apply(Attack(2,g.state.players[2].hero_id,g.state.players[1].hero_id));self.assertEqual(len(g.state.players[1].secrets),1)

    def test_own_turn_forced_enemy_attack_keeps_secret(self):
        g=self.game((VISAGE,FORCE),enemy=(UNIT,));self.play(g,VISAGE);self.play(g,FORCE)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(any(e.card_id==UNIT for e in self.units(g)))

    def test_full_board_keeps_secret_and_allocates_no_copy_root(self):
        g=self.game((VISAGE,),board=(FILL,)*7,enemy=(UNIT,));self.arm(g);self.hit(g)
        self.assertEqual(len(g.state.players[1].secrets),1);self.assertFalse(g.state.card_summon_history)

    def test_secret_reveal_wait_restore_and_rng_failure_rollback(self):
        g=self.game((VISAGE,),board=(WATCH,),enemy=(UNIT,),mode='reveal');self.arm(g);self.hit(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.settle(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.portable(g)

    def test_attacker_removed_during_reveal_never_copies_later_or_missing_body(self):
        g=self.game((VISAGE,),board=(WATCH,),enemy=(UNIT,),mode='reveal');self.arm(g);self.hit(g)
        g=self.portable(g);self.choose(g,'kill');self.assertFalse(any(e.card_id==UNIT for e in self.units(g)))
        self.assertFalse(g.state.players[1].secrets);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_actual_copy_summon_wait_and_bounced_delivery_cannot_attack(self):
        g=self.game((VISAGE,),board=(WATCH,),enemy=(UNIT,),mode='summon');self.arm(g);self.hit(g)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g,'bounce')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertFalse(any(e.card_id==UNIT for e in self.units(g)));self.assertEqual(self.entity(g,UNIT,1).zone,Zone.HAND);self.portable(g)

    def test_actual_copy_summon_wait_success_uses_original_delivery(self):
        g=self.game((VISAGE,),board=(WATCH,),enemy=(UNIT,),mode='summon');self.arm(g);self.hit(g)
        g=self.settle(g);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.portable(g)

    def test_zero_schools_pays_seven_but_has_no_rng_or_summon(self):
        g=self.game((INSPIRATION,));before=g.snapshot()['rng_state'];self.play(g,INSPIRATION)
        self.assertEqual(g.state.players[1].mana,33);self.assertFalse(self.vortex(g));self.assertFalse(self.randoms(g))
        self.assertEqual(g.snapshot()['rng_state'],before);self.portable(g)

    def test_duplicate_and_unschooled_casts_count_once(self):
        g=self.game((SPELLS[0],SPELLS[0],OTHER,INSPIRATION))
        self.play(g,SPELLS[0]);self.play(g,SPELLS[0]);self.play(g,OTHER)
        self.assertEqual(count_distinct_cast_schools(g.state,g.registry,1),1);self.play(g,INSPIRATION)
        self.assertEqual((len(self.vortex(g)),len(self.randoms(g))),(1,1))

    def test_automatic_repeated_casts_count_and_opponent_schools_stay_separate(self):
        g=self.game((AUTO,OTHER,INSPIRATION));self.play(g,AUTO);self.play(g,OTHER)
        self.assertEqual((count_distinct_cast_schools(g.state,g.registry,1),count_distinct_cast_schools(g.state,g.registry,2)),(1,1))
        self.play(g,INSPIRATION);self.assertEqual(len(self.vortex(g)),1);self.portable(g)

    def test_seven_distinct_actual_schools_produce_seven_original_requests(self):
        self.assertEqual(len(SPELLS),7);g=self.game((*SPELLS,INSPIRATION))
        for cid in SPELLS:self.play(g,cid)
        self.play(g,INSPIRATION);self.assertEqual((len(self.vortex(g)),len(self.randoms(g))),(7,7))
        self.assertEqual(len(g.state.card_summon_history),7)
        for e in self.randoms(g):self.assertEqual(tuple(dict(e.data)['candidates']),native.VORTICES)

    def test_random_variant_uses_full_order_and_ordinary_uniform_rng(self):
        g=self.game((SPELLS[0],INSPIRATION));self.play(g,SPELLS[0]);rng=Random();rng.setstate(g._rng.getstate())
        expected=rng.choice(native.VORTICES);self.play(g,INSPIRATION)
        self.assertEqual(self.vortex(g)[0].card_id,expected);self.assertEqual(g._rng.getstate(),rng.getstate())

    def test_all_eight_random_outcomes_actually_enter_with_one_printed_keyword(self):
        seen=set()
        for seed in range(80):
            g=self.game((SPELLS[0],INSPIRATION),seed=seed);self.play(g,SPELLS[0]);self.play(g,INSPIRATION)
            unit=self.vortex(g)[0];seen.add(unit.card_id);self.assertEqual((unit.attack,unit.health),(4,5))
            self.assertEqual(tuple(unit.keywords),registry().card(unit.card_id).keywords)
            if len(seen)==8:break
        self.assertEqual(seen,set(native.VORTICES))

    def test_full_board_still_chooses_each_original_request_without_deliveries(self):
        g=self.game((SPELLS[0],SPELLS[1],INSPIRATION),board=(FILL,)*7)
        self.play(g,SPELLS[0]);self.play(g,SPELLS[1]);self.play(g,INSPIRATION)
        self.assertEqual(len(self.randoms(g)),2);self.assertFalse(self.vortex(g))
        self.assertEqual(len(g.state.card_summon_history),2);self.portable(g)

    def test_last_slot_does_not_crop_full_variant_candidates_or_later_requests(self):
        g=self.game((SPELLS[0],SPELLS[1],INSPIRATION),board=(FILL,)*6)
        self.play(g,SPELLS[0]);self.play(g,SPELLS[1]);self.play(g,INSPIRATION)
        self.assertEqual((len(self.vortex(g)),len(self.randoms(g))),(1,2))
        self.assertTrue(all(tuple(dict(e.data)['candidates'])==native.VORTICES for e in self.randoms(g)))

    def test_existing_quantity_expansion_keeps_the_selected_native_face(self):
        g=self.game((SPELLS[0],INSPIRATION),board=(DOUBLE,));self.play(g,SPELLS[0]);self.play(g,INSPIRATION)
        self.assertEqual((len(self.vortex(g)),len(self.randoms(g))),(2,1))
        self.assertEqual(len({e.card_id for e in self.vortex(g)}),1);self.portable(g)

    def test_random_choice_wait_restores_before_original_selected_summon(self):
        g=self.game((SPELLS[0],INSPIRATION),board=(WATCH,),mode='random');self.play(g,SPELLS[0]);self.play(g,INSPIRATION)
        self.assertIsNotNone(g.state.pending_choice);g=self.settle(g);self.assertEqual(len(self.vortex(g)),1);self.portable(g)

    def test_summon_reaction_new_school_does_not_increase_frozen_original_count(self):
        g=self.game((SPELLS[0],INSPIRATION),board=(WATCH,),mode='summon');self.play(g,SPELLS[0]);self.play(g,INSPIRATION)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g,'school')
        self.assertEqual(count_distinct_cast_schools(g.state,g.registry,1),2)
        self.assertEqual((len(self.vortex(g)),len(self.randoms(g))),(1,1));self.portable(g)

    def test_complete_local_host_real_secret_attack_and_actual_inspiration(self):
        r=host()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(VISAGE,),mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=(native.VORTICES[0],),deck=(native.VORTICES[0],)*3)),seed=9),r)
        self.play(g,VISAGE);g.apply(EndTurn(1));unit=g.state.players[2].board[0]
        g.apply(Attack(2,unit,g.state.players[1].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('CS2_029',INSPIRATION),mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08')),seed=10),r)
        self.play(g,'CS2_029',g.state.players[2].hero_id);self.play(g,INSPIRATION)
        self.assertEqual(len(self.vortex(g)),1);self.assertTrue(set(native.DEPENDENCIES)<=set(r.pool_cards))


if __name__=='__main__':unittest.main()
