"""Borrowed damage follows its actual passive power, including saved health work."""
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.rajh_known_passive_pool import CARD
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayerSetup,
    ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.assemble_faces import recipe_from_id
from hs_sim.engine.assembled_powers import power_recipe_from_id
from hs_sim.engine.effects import ChoiceOption, Damage, InvokeBehavior, RequestChoice
from hs_sim.engine.model import DamageKind, HealthFlow, HealthOp, HealthRule
from hs_sim.local_pool_format import build_cn37_local_pool_format

P='k571.damage.'
BOOST,UNIT,WATCH,FAULT,BAD=(P+x for x in ('boost','unit','watch','fault','bad'))


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    fmt=build_cn37_local_pool_format();r=fmt.registry
    r.register_card(CardDefinition(BOOST,BOOST,CardType.MINION,attack=1,health=20,spell_damage=5,
        health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.ADD,1,source_relation='friendly',
            damage_kinds=(DamageKind.HERO_POWER,)),)))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=20))
    def fail(c):raise ResolutionError('k571 deliberate health resume failure')
    r.register_behavior(FAULT,fail)
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if mode!='wait' or source is None or not source.card_id.startswith('assemble-power:'):return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
        triggers=(TriggerSpec('health_resolved',WATCH),)))
    r.register_behavior(BAD,lambda c:(Damage(c.state.players[2].hero_id,1,
        c.state.players[1].hero_power_id,DamageKind.MINION_ABILITY),))
    r.register_card(CardDefinition(BAD,BAD,CardType.SPELL,on_play=BAD))
    r.validate();return r,fmt


class RajhPassiveDamageSourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:fixture(mode,role)[0])

    def game(self,mode='normal'):
        self.mode=mode;r,fmt=fixture(mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_04',hero_power_card_id='HERO_04bp',
            hand=(CARD,BAD),board=(BOOST,)+((WATCH,)if mode=='wait'else()),deck=(UNIT,)*8,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=(UNIT,UNIT),deck=(UNIT,)*8)),seed=95,generation_context=fmt.context),r)

    def install(self,g):
        self.play(g,CARD)
        option=next(o for o in g.state.pending_choice.options
            if (lambda p:p.primary_card_id=='TLC_623'and p.secondary_card_id=='CORE_RLK_083'and p.half=='bottom')(
                recipe_from_id(power_recipe_from_id(o.card_id).minion_card_id)))
        self.choose(g,option.id);return g.state.players[1].hero_power_id

    def dealt(self,g,power):
        return[e for e in g.events if e.kind=='damage_dealt'and e.source_id==power]

    def test_passive_damage_is_power_damage_with_its_bonus_and_without_spell_damage_or_use(self):
        g=self.game();power=self.install(g);g.apply(EndTurn(1));rows=self.dealt(g,power)
        self.assertEqual(len(rows),2);self.assertEqual([e.amount for e in rows],[2,2])
        self.assertEqual({dict(e.data)['damage_kind']for e in rows},{'hero_power'})
        self.assertFalse(g.state.hero_power_history);self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(g.state.players[1].mana,5);self.portable(g)

    def test_ordinary_power_cannot_impersonate_a_minion_ability_source(self):
        g=self.game();saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Minion ability damage requires a minion source'):
            self.play(g,BAD)
        self.assertEqual(g.snapshot(),saved)

    def test_prepared_passive_health_result_wait_restores_kind_bonus_and_failure_atomicity(self):
        g=self.game('wait');power=self.install(g);g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,restored):
            while current.state.pending_choice:self.choose(current)
            self.assertEqual([e.amount for e in self.dealt(current,power)],[2,2])
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)


if __name__=='__main__':unittest.main()
