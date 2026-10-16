"""One real SPELL budget, independent recipient rules and atomic health settlement."""
from dataclasses import asdict, replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.excess_secret_cards import load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.damage_history import spell_damage_dealt
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.excess_damage import DamageExcessToHero, prepare_partition
from hs_sim.engine.health_rules import rule_sources
from hs_sim.engine.model import DamageKind, HealthFlow, HealthLayer, HealthOp, HealthRule, SpellSchool
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest


def registry(mode=None, hero_immune=False):
    r=build_registry(); meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_card(CardDefinition('k13b.hero','Hero',CardType.HERO,health=100,metadata=meta,
        keywords=(Keyword.IMMUNE,)if hero_immune else ()))
    for hp in (1,3,4,6,9):
        r.register_card(CardDefinition('k13b.minion'+str(hp),'Minion',CardType.MINION,cost=3,attack=1,health=hp,metadata=meta))
    r.register_card(CardDefinition('k13b.shield','Shield',CardType.MINION,cost=3,attack=1,health=3,
        keywords=(Keyword.DIVINE_SHIELD,),metadata=meta))
    r.register_card(CardDefinition('k13b.immune','Immune',CardType.MINION,cost=3,attack=1,health=3,
        keywords=(Keyword.IMMUNE,),metadata=meta))
    for cid,school in (('bonus',()),('fire',(SpellSchool.FIRE,)),('frost',(SpellSchool.FROST,))):
        r.register_card(CardDefinition('k13b.'+cid,cid,CardType.MINION,health=10,spell_damage=2,
            spell_damage_schools=school,metadata=meta))
    rules={
        'source_double':HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,source_relation='friendly',damage_kinds=(DamageKind.SPELL,)),
        'target_double':HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,layer=HealthLayer.TARGET,
            target_kinds=(CardType.MINION,),damage_kinds=(DamageKind.SPELL,)),
        'target_prevent':HealthRule(HealthFlow.DAMAGE,HealthOp.PREVENT,layer=HealthLayer.TARGET,
            target_kinds=(CardType.MINION,),damage_kinds=(DamageKind.SPELL,)),
        'floor':HealthRule(HealthFlow.DAMAGE,HealthOp.FLOOR,1,layer=HealthLayer.TARGET,
            target_kinds=(CardType.MINION,),damage_kinds=(DamageKind.SPELL,)),
        'convert':HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT,source_relation='friendly',damage_kinds=(DamageKind.SPELL,)),
        'redirect':HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,
            target_relation='enemy',target_kinds=(CardType.HERO,),redirect_to='self'),
    }
    for cid,rule in rules.items():
        r.register_card(CardDefinition('k13b.'+cid,cid,CardType.MINION,health=20,health_rules=(rule,),metadata=meta))
    r.register_behavior('k13b.fail',lambda c:(AddToHand(c.player_id,'missing.k13b'),))
    r.register_behavior('k13b.self',lambda c:(Damage(c.state.players[c.player_id].hero_id,4,c.source_id),))
    r.register_card(CardDefinition('k13b.self','Self wound',CardType.SPELL,on_play='k13b.self',metadata=meta))
    r.register_behavior('k13b.noop',lambda c:())
    r.register_card(CardDefinition('k13b.noop','Noop',CardType.SPELL,on_play='k13b.noop',metadata=meta))
    if mode:
        def watch(c):
            if mode=='shift' and c.event.kind=='secret_revealed':
                target=c.state.players[2].board[-1]
                return (ReturnToHand(target),)
            if mode=='transform' and c.event.kind=='secret_revealed':
                return (Transform(c.state.players[2].board[-1],'k13b.minion9'),)
            if mode=='wait' and c.event.kind=='damage_dealt' and c.event.target_id==c.state.players[2].hero_id:return ()
            if mode=='wait' and c.event.kind=='damage_dealt':
                return (RequestChoice(c.player_id,(
                    ChoiceOption('continue','Continue after both parcels'),
                    ChoiceOption('bad','Rollback',(InvokeBehavior('k13b.fail',c.source_id,c.player_id),)),
                ),c.source_id),)
            return ()
        r.register_behavior('k13b.watch',watch)
        r.register_card(CardDefinition('k13b.watch','Observer',CardType.MINION,health=10,
            triggers=tuple(TriggerSpec(e,'k13b.watch')for e in ('secret_revealed','damage_dealt')),metadata=meta))
    return r


class ExcessSecretCardTests(unittest.TestCase):
    def game(self, target='k13b.minion3', board=(), mode=None, armor=0, hero_immune=False):
        self.mode,self.hero_immune=mode,hero_immune
        return Game.from_scenario(Scenario((
            PlayerSetup('k13b.hero',hand=('CORE_LOOT_101',),board=board,deck=('k13b.noop',)*5,
                        mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('k13b.hero',hand=(target,'k13b.self'),deck=('k13b.noop',)*5,
                        mana=30,max_mana=30,mana_cap=30,armor=armor)),seed=223),registry(mode,hero_immune))
    def eid(self,g,cid,p):return next(e for e in g.state.players[p].hand if g.state.entities[e].card_id==cid)
    def play(self,g,cid,p):
        eid=self.eid(g,cid,p);g.apply(PlayCard(p,eid));return eid
    def trigger(self,g,target='k13b.minion3',wound=False):
        self.play(g,'CORE_LOOT_101',1);g.apply(EndTurn(1))
        if wound:self.play(g,'k13b.self',2)
        return self.play(g,target,2)
    def hero(self,g,p=2):return g.state.entities[g.state.players[p].hero_id]
    def rows(self,g):return [x.health_result for x in g.state.damage_history if x.health_result.source_card_id=='CORE_LOOT_101']
    def portable(self,g):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(self.mode,self.hero_immune))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(self.mode,self.hero_immune)).snapshot(),saved);return other
    def finish(self,g,option='continue'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))

    def test_full_current_runes_pin_and_normal_secret_payment(self):
        row=load_batch()['cards'][0];self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        g=self.game();self.play(g,'CORE_LOOT_101',1)
        self.assertEqual((g.registry.card('CORE_LOOT_101').spell_school,g.state.players[1].mana),(SpellSchool.FIRE,27))
        self.assertEqual(len(g.state.players[1].secrets),1);self.portable(g)

    def test_exact_hp_partition_assigns_six_total_without_duplicate_excess(self):
        for hp,expected in ((1,[1,5]),(3,[3,3]),(6,[6]),(9,[6])):
            with self.subTest(hp=hp):
                cid='k13b.minion'+str(hp);g=self.game(cid);self.trigger(g,cid)
                self.assertEqual([r.damage_dealt for r in self.rows(g)],expected)
                self.assertEqual(self.hero(g).health,100-max(0,6-hp))
                self.assertEqual(spell_damage_dealt(g.state,g.registry,1,turn=2),6);self.portable(g)

    def test_one_spell_bonus_budget_uses_matching_school_once(self):
        for provider,total in (('bonus',8),('fire',8),('frost',6)):
            with self.subTest(provider=provider):
                g=self.game(board=('k13b.'+provider,));self.trigger(g)
                self.assertEqual([r.damage_dealt for r in self.rows(g)],[3,total-3])
                self.assertEqual(spell_damage_dealt(g.state,g.registry,1,turn=2),total);self.portable(g)

    def test_source_multiplier_is_quoted_once_before_recipient_partition(self):
        g=self.game(board=('k13b.bonus','k13b.source_double'));self.trigger(g)
        self.assertEqual([r.damage_dealt for r in self.rows(g)],[3,13])
        self.assertEqual(self.hero(g).health,87);self.portable(g)

    def test_target_multiplier_does_not_expand_preassigned_hero_remainder(self):
        g=self.game(board=('k13b.target_double',));self.trigger(g)
        self.assertEqual([r.damage_dealt for r in self.rows(g)],[6,3])
        self.assertEqual(self.hero(g).health,97);self.portable(g)

    def test_divine_shield_stops_only_minion_parcel_hero_still_takes_remainder(self):
        g=self.game('k13b.shield');target=self.trigger(g,'k13b.shield')
        self.assertEqual((g.state.entities[target].health,self.hero(g).health),(3,97))
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords)
        self.assertEqual([r.damage_dealt for r in self.rows(g)],[0,3]);self.portable(g)

    def test_minion_immunity_and_target_prevention_do_not_reallocate_remainder(self):
        for cid,board in (('k13b.immune',()),('k13b.minion3',('k13b.target_prevent',))):
            g=self.game(cid,board);target=self.trigger(g,cid)
            self.assertEqual((g.state.entities[target].health,self.hero(g).health),(3,97))
            self.assertEqual([r.damage_dealt for r in self.rows(g)],[0,3]);self.portable(g)

    def test_hero_armor_and_immunity_apply_to_only_assigned_hero_parcel(self):
        g=self.game(armor=10);self.trigger(g)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(100,7))
        self.assertEqual((self.rows(g)[1].damage_dealt,self.rows(g)[1].armor_absorbed),(3,3));self.portable(g)
        g=self.game(hero_immune=True);self.trigger(g)
        self.assertEqual([r.damage_dealt for r in self.rows(g)],[3,0]);self.portable(g)

    def test_minion_health_floor_does_not_increase_hero_parcel(self):
        g=self.game(board=('k13b.floor',));target=self.trigger(g)
        self.assertEqual((g.state.entities[target].health,self.hero(g).health),(1,97))
        self.assertEqual([r.damage_dealt for r in self.rows(g)],[2,3]);self.portable(g)

    def test_secondary_redirection_reuses_original_rules_without_recomputing_budget(self):
        g=self.game(board=('k13b.redirect',));redirect=g.state.players[1].board[0];self.trigger(g)
        rows=self.rows(g);self.assertEqual(rows[1].original_target_id,g.state.players[2].hero_id)
        self.assertEqual((rows[1].target_id,g.state.entities[redirect].health,self.hero(g).health),(redirect,17,100))
        self.portable(g)

    def test_source_conversion_is_preserved_without_double_conversion_or_bonus(self):
        g=self.game(board=('k13b.convert',));target=self.trigger(g,wound=True)
        rows=self.rows(g);self.assertTrue(all(r.converted and r.flow=='healing' for r in rows))
        self.assertEqual((g.state.entities[target].health,self.hero(g).health),(3,99));self.portable(g)

    def test_both_parcels_settle_before_original_death_or_damage_reactions(self):
        g=self.game(board=('k13b.watch',),mode='wait');target=self.trigger(g)
        self.assertEqual(self.hero(g).health,97);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(self.rows(g)),2);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len({r.batch_id for r in self.rows(g)}),1)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.finish(g,'bad')
        self.assertEqual(g.snapshot(),saved);other=self.portable(g)
        self.finish(g);self.finish(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(len(self.rows(g)),2);self.assertEqual(self.hero(g).health,97);self.portable(g)

    def test_original_minion_reference_stales_after_reveal_return_or_transform(self):
        for mode in ('shift','transform'):
            g=self.game(board=('k13b.watch',),mode=mode);self.trigger(g)
            self.assertEqual(self.hero(g).health,100);self.assertFalse(self.rows(g));self.portable(g)

    def test_partition_quote_is_pure_and_original_request_codec_is_portable(self):
        g=self.game();self.play(g,'CORE_LOOT_101',1)
        source=g.state.players[1].secrets[0]
        # A physical board fixture supplies a direct public request without executing it.
        r=registry();r.register_behavior('k13b.put',lambda c:())
        h=Game.from_scenario(Scenario((PlayerSetup('k13b.hero',board=('k13b.minion3',)),
            PlayerSetup('k13b.hero',hand=('CORE_LOOT_101',)))),r)
        target=h.state.entities[h.state.players[1].board[0]];source=self.eid(h,'CORE_LOOT_101',2)
        request=DamageExcessToHero(MinionReference.capture(target),6,source)
        saved=h.snapshot();instructions,packets=prepare_partition(h.state,h.registry,request,rule_sources(h.state))
        self.assertEqual([p.amount for p in packets],[3,3]);self.assertEqual(h.snapshot(),saved)
        codec=FrameCodec(h.mechanics,h.registry);self.assertEqual(codec.decode(codec.encode(request)),request)

    def test_unknown_callback_is_rejected_even_when_original_reference_is_stale(self):
        g=self.game();source=self.eid(g,'CORE_LOOT_101',1)
        request=DamageExcessToHero(MinionReference(999,2,'k13b.minion3',1,1),6,source,on_result='unknown.k13b')
        with self.assertRaises(ValueError):prepare_partition(g.state,g.registry,request,rule_sources(g.state))

    def test_partition_public_request_validation_is_strict(self):
        ref=MinionReference(1,1,'k13b.minion3',0,1)
        for make in (lambda:DamageExcessToHero(ref,-1,2),lambda:DamageExcessToHero(ref,True,2),
                     lambda:DamageExcessToHero(ref,6,None),lambda:DamageExcessToHero('bad',6,2)):
            with self.assertRaises(ValueError):make()

    def test_player_projection_exposes_results_without_private_partition_operands(self):
        g=self.game(board=('k13b.watch',),mode='wait');self.trigger(g)
        for player in (1,2):
            public=json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for field in ('partition_source','source_keywords','rule_ids','zone_epoch','payment_state'):
                self.assertNotIn('"'+field+'"',public)


if __name__=='__main__':unittest.main()
