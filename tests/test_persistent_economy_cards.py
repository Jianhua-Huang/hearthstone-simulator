"""Actual lasting economy cards share existing quotes, openings and health rules."""
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.persistent_economy_cards import load_batch,HEALING_BONUS
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,
    DeckSpec,EndTurn,Game,HealingKind,Keyword,MatchSetup,OpeningHook,PlayCard,
    PlayerSetup,Rarity,Scenario,SelectChoice,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,CostSpec,Damage,
    Destroy,Heal,InvokeBehavior,ReplaceHero,ReplaceHeroPower,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

ROOTS=('CORE_DRG_403','EDR_847','TLC_257','EDR_000','CATA_216')


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_card(CardDefinition('k25.hero','Replacement',CardType.HERO,health=30,metadata=meta))
    r.register_card(CardDefinition('k25.body','Body',CardType.MINION,cost=2,attack=2,health=5,metadata=meta))
    r.register_card(CardDefinition('k25.leech','Lifesteal',CardType.MINION,attack=2,health=5,
        keywords=(Keyword.CHARGE,Keyword.LIFESTEAL),metadata=meta))
    scripts={
        'wound':lambda c:tuple(Damage(c.state.players[p].hero_id,10,c.source_id) for p in (1,2)),
        'heal':lambda c:(Heal(c.target_id or c.state.players[c.player_id].hero_id,2,c.source_id,HealingKind.SPELL),),
        'heal_effect':lambda c:(Heal(c.target_id or c.state.players[c.player_id].hero_id,2,c.source_id,HealingKind.EFFECT),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'new':lambda c:(AddToHand(c.player_id,'k25.body'),),
        'summon':lambda c:(Summon(c.player_id,'EDR_847'),),
        'replace':lambda c:(ReplaceHero(c.player_id,'k25.hero',hero_power_card_id='HERO_08bp'),),
        'power':lambda c:(ReplaceHeroPower(c.player_id,'HERO_08bp',source_id=c.source_id),),
        'discount':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.MINION,)),source_id=c.source_id),),
    }
    for name,fn in scripts.items():
        r.register_behavior('k25.'+name,fn)
        from hs_sim.engine import TargetSpec
        targeted=name in ('heal','heal_effect','kill','silence')
        r.register_card(CardDefinition('k25.'+name,name,CardType.SPELL,on_play='k25.'+name,
            targeting=TargetSpec() if targeted else None,metadata=meta))
    r.register_behavior('k25.healpower',lambda c:(Heal(c.state.players[c.player_id].hero_id,2,c.source_id,HealingKind.HERO_POWER),))
    r.register_card(CardDefinition('k25.healpower','Healing power',CardType.HERO_POWER,cost=2,on_use='k25.healpower',metadata=meta))
    r.register_behavior('k25.fail',lambda c:(AddToHand(c.player_id,'missing.k25.fail'),))
    def waiting(c):
        if c.event is not None and (c.event.source_id is None or c.state.entities[c.event.source_id].card_id not in ROOTS):return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('bad','Rollback',(InvokeBehavior('k25.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k25.wait',waiting)
    r.register_card(CardDefinition('k25.openwait','Opening observer',CardType.MINION,health=1,
        metadata=replace(meta,collectible=True,rarity=Rarity.COMMON),
        opening_hooks=(OpeningHook('before_deal','k25.wait'),)))
    if mode=='commit':
        r.register_card(CardDefinition('k25.watch','Observer',CardType.MINION,health=10,metadata=meta,
            triggers=(TriggerSpec('card_committed','k25.wait'),)))
    if mode=='installed':
        r.register_card(CardDefinition('k25.watch','Observer',CardType.MINION,health=10,metadata=meta,
            triggers=(TriggerSpec('cost_modifier_added','k25.wait'),TriggerSpec('ability_granted','k25.wait'))))
    return r


class PersistentEconomyCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy_hand=(),enemy_board=(),mode=None,power='HERO_08bp',mana=40,cap=40):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*8,mana=mana,max_mana=mana,
                mana_cap=cap,hero_power_card_id=power),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('CORE_CS2_182',)*8,mana=mana,
                max_mana=mana,mana_cap=cap,hero_power_card_id='HERO_08bp')),seed=379),registry(mode) if mode else self.r)
    def eid(self,g,cid,p=1,zone='hand'):
        return next(e for e in getattr(g.state.players[p],zone) if g.state.entities[e].card_id==cid)
    def play(self,g,cid,target=None,p=None):
        p=p or g.state.active_player;e=self.eid(g,cid,p);g.apply(PlayCard(p,e,target_id=target));return e
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def quote(self,g,cid,p=1):
        s=g.state;return quote_cost(s,g.registry,s.entities[self.eid(g,cid,p)])
    def power_quote(self,g,p=1):
        s=g.state;return quote_cost(s,g.registry,s.entities[s.players[p].hero_power_id])
    def use(self,g,p=None):
        p=p or g.state.active_player;g.apply(UseHeroPower(p,g.state.players[p].hero_power_id,g.state.players[3-p].hero_id))
    def portable(self,g):
        s=g.snapshot();other=Game.from_snapshot(s,registry(self.mode))
        self.assertEqual(s,other.snapshot());self.assertEqual(s,g.clone().snapshot())
        self.assertEqual(s,replay(build_replay(g),registry(self.mode)).snapshot());return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def opening(self,first=('EDR_000',),second=(),*,wait=False):
        self.mode=None;r=registry();first=(*first,*(('k25.openwait',) if wait else ()))
        decks=tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,(*part,*('CORE_CS2_182',)*(8-len(part)))) for part in (first,second))
        policy=DeckPolicy('k25-opening','fixed-evidence','experimental',tuple(r.cards),deck_size=8,max_copies=8)
        return Game.from_decks(MatchSetup(decks,policy,'GAME_005',seed=380,first_player=1),r)
    def finish_opening(self,g):
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))

    def test_full_pinned_records_stats_identity_and_complete_entries(self):
        rows=load_batch()['cards'];self.assertEqual(len(rows),5)
        for row in rows:
            raw,recipe=row['record'],row['recipe'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            card=self.r.card(raw['id']);self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
            self.assertEqual(card.metadata.deck_identity,recipe['deck_identity']);self.assertIsNotNone(card.battlecry)
        self.assertIsNotNone(self.r.card('EDR_847').deathrattle)
        self.assertEqual(self.r.card('EDR_000').opening_hooks[0].phase,'before_deal')

    def test_blowtorch_taxes_opponent_only_and_payment_consumes_once(self):
        g=self.game(('CORE_DRG_403',),enemy_hand=('CORE_EX1_008',));self.play(g,'CORE_DRG_403')
        self.assertEqual((self.power_quote(g).amount,self.power_quote(g,2).amount),(2,4));g.apply(EndTurn(1))
        self.play(g,'CORE_EX1_008');self.assertEqual(self.power_quote(g,2).amount,4)
        mana=g.state.players[2].mana;self.use(g)
        self.assertEqual(g.state.players[2].mana,mana-4);self.assertEqual(self.power_quote(g,2).amount,2);self.portable(g)

    def test_blowtorch_source_death_and_unused_turns_do_not_expire(self):
        g=self.game(('CORE_DRG_403','k25.kill'));e=self.play(g,'CORE_DRG_403');self.play(g,'k25.kill',e)
        for p in (1,2,1):g.apply(EndTurn(p))
        self.assertEqual(self.power_quote(g,2).amount,4);self.use(g);self.assertEqual(self.power_quote(g,2).amount,2)

    def test_blowtorch_instances_stack_and_one_use_spends_each(self):
        g=self.game(('CORE_DRG_403','CORE_DRG_403'));self.play(g,'CORE_DRG_403');self.play(g,'CORE_DRG_403')
        g.apply(EndTurn(1));self.assertEqual(self.power_quote(g,2).amount,6)
        self.use(g);self.assertFalse(g.state.players[2].cost_modifiers);self.portable(g)

    def test_illegal_power_does_not_consume_tax_or_change_state(self):
        g=self.game(('CORE_DRG_403',));self.play(g,'CORE_DRG_403');g.apply(EndTurn(1));saved=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(2,g.state.players[2].hero_power_id,999999))
        self.assertEqual(saved,g.snapshot());self.assertEqual(self.power_quote(g,2).amount,4)

    def test_disciple_battlecry_then_original_death_each_install_zero(self):
        g=self.game(('EDR_847','k25.kill'));e=self.play(g,'EDR_847')
        self.assertEqual(self.power_quote(g).amount,0);mana=g.state.players[1].mana;self.use(g)
        self.assertEqual(g.state.players[1].mana,mana);self.assertFalse(g.state.players[1].cost_modifiers)
        self.play(g,'k25.kill',e);self.assertEqual(self.power_quote(g).amount,0);self.portable(g)

    def test_disciple_summon_skips_battlecry_but_keeps_deathrattle(self):
        g=self.game(('k25.summon','k25.kill'));self.play(g,'k25.summon');self.assertEqual(self.power_quote(g).amount,2)
        self.play(g,'k25.kill',self.eid(g,'EDR_847',zone='board'));self.assertEqual(self.power_quote(g).amount,0)

    def test_disciple_silence_removes_only_future_deathrattle(self):
        g=self.game(('EDR_847','k25.silence','k25.kill'));e=self.play(g,'EDR_847');self.use(g)
        self.play(g,'k25.silence',e);self.play(g,'k25.kill',e);self.assertEqual(self.power_quote(g).amount,2)

    def test_disciple_death_before_use_adds_two_layers_consumed_together(self):
        g=self.game(('EDR_847','k25.kill'));e=self.play(g,'EDR_847');self.play(g,'k25.kill',e)
        self.assertEqual(len(g.state.players[1].cost_modifiers),2);self.assertEqual(self.power_quote(g).amount,0)
        self.use(g);self.assertEqual(self.power_quote(g).amount,2);self.assertFalse(g.state.players[1].cost_modifiers)

    def test_hero_and_power_replacement_preserve_next_power_zero(self):
        g=self.game(('EDR_847','k25.power','k25.replace'));self.play(g,'EDR_847')
        old=g.state.players[1].hero_power_id;self.play(g,'k25.power');self.assertNotEqual(old,g.state.players[1].hero_power_id)
        self.play(g,'k25.replace');self.assertEqual(self.power_quote(g).amount,0);self.use(g);self.portable(g)

    def test_real_tax_then_zero_order_uses_original_shared_cost_layers(self):
        g=self.game(('CORE_DRG_403',),enemy_hand=('EDR_847',));self.play(g,'CORE_DRG_403');g.apply(EndTurn(1))
        self.play(g,'EDR_847');self.assertEqual(self.power_quote(g,2).amount,0);self.use(g)
        self.assertFalse(g.state.players[2].cost_modifiers)

    def test_lo_sets_cheaper_and_more_expensive_current_and_future_minions(self):
        g=self.game(('TLC_257','CORE_EX1_008','EDR_000','k25.new','CORE_CS2_029'))
        e=self.play(g,'TLC_257');self.assertEqual(self.quote(g,'CORE_EX1_008').amount,5)
        self.assertEqual(self.quote(g,'EDR_000').amount,5);self.assertEqual(self.quote(g,'CORE_CS2_029').amount,4)
        self.assertEqual(self.power_quote(g).amount,2);self.play(g,'k25.new');self.assertEqual(self.quote(g,'k25.body').amount,5)
        self.assertEqual(g.state.entities[e].cost,9);self.portable(g)

    def test_lo_source_silence_death_and_hero_replacement_preserve_player_cost(self):
        g=self.game(('TLC_257','k25.silence','k25.kill','k25.replace','CORE_EX1_008'))
        e=self.play(g,'TLC_257');self.play(g,'k25.silence',e);self.play(g,'k25.kill',e);self.play(g,'k25.replace')
        self.assertEqual(self.quote(g,'CORE_EX1_008').amount,5);self.portable(g)

    def test_lo_before_and_after_discount_follow_existing_attachment_order(self):
        g=self.game(('k25.discount','TLC_257','k25.discount','CORE_CS2_182'));self.play(g,'k25.discount')
        self.play(g,'TLC_257');self.assertEqual(self.quote(g,'CORE_CS2_182').amount,5)
        self.play(g,'k25.discount');self.assertEqual(self.quote(g,'CORE_CS2_182').amount,3);self.portable(g)

    def test_ysera_actual_opening_increases_both_caps_without_giving_crystals(self):
        g=self.opening();self.assertEqual([p.mana_cap for p in g.state.players.values()],[15,15])
        self.assertEqual([p.max_mana for p in g.state.players.values()],[0,0]);self.portable(g)
        self.finish_opening(g);self.assertEqual([p.max_mana for p in g.state.players.values()],[1,0]);self.portable(g)

    def test_ysera_both_original_decks_add_independent_five_caps(self):
        g=self.opening(second=('EDR_000',));self.assertEqual([p.mana_cap for p in g.state.players.values()],[20,20])
        self.assertEqual(sum(e.kind=='opening_effect' for e in g.events),2);self.finish_opening(g);self.portable(g)

    def test_ysera_scenario_and_normal_battlecry_do_not_fake_start_game(self):
        g=self.game(('EDR_000',),mana=9,cap=15);self.assertEqual(g.state.players[1].mana_cap,15)
        self.play(g,'EDR_000');self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(12,3))
        self.assertEqual(g.state.players[2].max_mana,9);self.assertFalse(any(e.kind=='opening_effect'for e in g.events));self.portable(g)

    def test_ysera_filled_crystals_stop_at_existing_cap(self):
        g=self.game(('EDR_000',),mana=9,cap=10);self.play(g,'EDR_000')
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(10,1));self.portable(g)

    def test_opening_wait_resume_does_not_repeat_ysera_or_deal_early(self):
        g=self.opening(wait=True);self.assertEqual(g.state.opening.stage,'dealing');self.assertEqual(g.state.players[1].mana_cap,15)
        self.assertFalse(g.state.players[1].hand);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(saved,g.snapshot());other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana_cap,15)
        self.finish_opening(g);self.portable(g)

    def test_purifier_boosts_own_spell_effect_and_skill_healing(self):
        for heal,power in (('k25.heal','HERO_08bp'),('k25.heal_effect','HERO_08bp'),(None,'k25.healpower')):
            g=self.game(('CATA_216','k25.wound',*( (heal,) if heal else ())),power=power)
            self.play(g,'CATA_216');self.play(g,'k25.wound');self.assertEqual(self.hero(g).health,20)
            if heal:self.play(g,heal,self.hero(g).id)
            else:g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
            self.assertEqual(self.hero(g).health,24);self.portable(g)

    def test_purifier_counts_source_not_target_and_does_not_boost_enemy_healer(self):
        g=self.game(('CATA_216','k25.wound','k25.heal'),enemy_hand=('k25.heal',))
        self.play(g,'CATA_216');self.play(g,'k25.wound');self.play(g,'k25.heal',self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,24);g.apply(EndTurn(1));self.play(g,'k25.heal',self.hero(g).id)
        self.assertEqual(self.hero(g).health,22);self.portable(g)

    def test_purifier_stack_source_death_silence_and_replaced_hero_keep_bonus(self):
        g=self.game(('CATA_216','CATA_216','k25.wound','k25.kill','k25.silence','k25.replace','k25.heal'))
        e=self.play(g,'CATA_216');self.play(g,'CATA_216');self.play(g,'k25.silence',e);self.play(g,'k25.kill',e)
        self.play(g,'k25.wound');old=self.hero(g).id;self.play(g,'k25.replace');self.assertNotEqual(old,self.hero(g).id)
        self.play(g,'k25.heal',self.hero(g).id);self.assertEqual(self.hero(g).health,26)
        self.assertEqual(sum(a.health_rule==HEALING_BONUS for a in self.hero(g).abilities if a.kind=='health_rule'),2);self.portable(g)

    def test_purifier_uses_shared_combat_lifesteal_and_actual_healing(self):
        g=self.game(('CATA_216','k25.wound','k25.leech'));self.play(g,'CATA_216');self.play(g,'k25.wound')
        leech=self.play(g,'k25.leech');g.apply(Attack(1,leech,self.hero(g,2).id))
        self.assertEqual(self.hero(g).health,24);self.assertEqual(self.hero(g,2).health,18);self.portable(g)

    def test_commit_wait_resumes_one_paid_install_and_bad_branch_rolls_back(self):
        for cid in ('CORE_DRG_403','EDR_847','TLC_257','CATA_216'):
            g=self.game((cid,),board=('k25.watch',),mode='commit');self.play(g,cid);self.assertIsNotNone(g.state.pending_choice)
            saved=g.snapshot();mana=g.state.players[1].mana
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(saved,g.snapshot());other=self.portable(g);self.choose(g);self.choose(other)
            self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana,mana)
            self.assertEqual(sum(e.kind=='mana_spent'for e in g.events),1)

    def test_player_projection_exposes_costs_without_private_rule_material(self):
        g=self.game(('TLC_257','CORE_EX1_008'),enemy_hand=('EDR_847',));self.play(g,'TLC_257')
        listing=g.for_player(1).legal_actions();self.assertIsNotNone(listing['actions'])
        own=next(p for p in listing['observation']['players']if p['id']==1)
        self.assertEqual(next(c['cost']['amount']for c in own['hand']if c['card_id']=='CORE_EX1_008'),5)
        public=json.dumps(g.for_player(1).observe())+json.dumps(g.player_events(1))
        for hidden in ('EDR_847','source_sha256','payment_state','cost_use_history'):
            self.assertNotIn(hidden,public)

    def test_installed_effect_wait_restore_does_not_duplicate_attachment(self):
        for cid in ('CORE_DRG_403','EDR_847','TLC_257','CATA_216'):
            g=self.game((cid,),board=('k25.watch',),mode='installed');self.play(g,cid)
            self.assertIsNotNone(g.state.pending_choice);saved=g.snapshot();other=self.portable(g)
            with self.assertRaises(ResolutionError):self.choose(g,'bad')
            self.assertEqual(saved,g.snapshot());self.choose(g);self.choose(other)
            self.assertEqual(g.snapshot(),other.snapshot())
            if cid=='CATA_216':
                self.assertEqual(sum(a.kind=='health_rule'and a.health_rule==HEALING_BONUS for a in self.hero(g).abilities),1)
            else:self.assertEqual(sum(len(p.cost_modifiers)for p in g.state.players.values()),1)
