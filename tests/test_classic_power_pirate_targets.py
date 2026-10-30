"""Real original entries, bounded Pirate quote and audited conditional arrows."""
from dataclasses import asdict,fields,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import build_registry,classic_power_pirate_targets as native
from hs_sim.cards.native_conditional_cards import register_native_conditional_cards
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,Draw,InvokeBehavior,RandomDamage,
    RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.model import (BoardMinionCostSpec,CardDefinition,CardType,Keyword,Rarity,TargetSpec,TribeChangeSpec,TriggerSpec,Zone)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

FIZZLE,KRAGG,REND,GORMOK,CENARIUS=native.ROOTS;TREANT=native.TREANT;HP='HERO_07bp';FANDRAL='CORE_OG_044'
P='k693.';A=P+'plain';PIRATE=P+'pirate';DRAGON=P+'dragon';ALL=P+'all';LEGEND=P+'legend'
DORMANT=P+'dormant';LOC=P+'location';POWER=P+'spell_power';WEAPON=P+'weapon';SPELL=P+'spell'
KILL=P+'kill';HUSH=P+'hush';DRAW=P+'draw';PIRATIZE=P+'piratize';REMOVE_PIRATE=P+'remove_pirate'
HELD_DRAGON=P+'held_dragon';HELD_PLAIN=P+'held_plain';FAIL=P+'fail';DOUBLE_HP=P+'double_power'
DRAW_WATCH=P+'draw_watch';COST_WATCH=P+'cost_watch';COMMIT_WATCH=P+'commit_watch'
SUMMON_WATCH=P+'summon_watch';DAMAGE_WATCH=P+'damage_watch';WATCH=P+'watch'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def static_fandral():
    r=build_registry();c=r.card(FANDRAL)
    assert c.choose_both and c.on_play is None and c.battlecry is None and not c.triggers
    return c,r.pool_card(FANDRAL)


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();register_native_conditional_cards(r);native.register_classic_power_pirate_targets(r)
    c,pool=static_fandral();r.register_card(c);r.register_pool_card(pool)
    for cid,tribes,rarity,bonus in((A,(),Rarity.COMMON,0),(PIRATE,('pirate',),Rarity.COMMON,0),
            (DRAGON,('dragon',),Rarity.COMMON,0),(ALL,('all',),Rarity.COMMON,0),
            (LEGEND,(),Rarity.LEGENDARY,0),(POWER,(),Rarity.COMMON,2)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=3,attack=2,health=10,spell_damage=bonus,
            metadata=replace(metadata(collectible=False),tribes=tribes,rarity=rarity)))
    r.register_card(CardDefinition(DORMANT,DORMANT,CardType.MINION,health=10,dormant_turns=2,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=3,attack=2,durability=2,metadata=metadata(collectible=False)))
    r.register_behavior(LOC,lambda c:());r.register_card(CardDefinition(LOC,LOC,CardType.LOCATION,cost=3,durability=3,on_use=LOC,metadata=metadata(collectible=False)))
    r.register_behavior(DOUBLE_HP,lambda c:(Draw(c.player_id,2,c.source_id),));r.register_card(CardDefinition(DOUBLE_HP,DOUBLE_HP,CardType.HERO_POWER,cost=2,on_use=DOUBLE_HP))
    def held(c,operation):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==A)
        return(ChangeMinionTribes(CardReference.capture(e),TribeChangeSpec(operation,('dragon',)),c.source_id),)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),SPELL:lambda c:(),
        PIRATIZE:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('add',('pirate',)),c.source_id),),
        REMOVE_PIRATE:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('remove',('pirate',)),c.source_id),),
        HELD_DRAGON:lambda c:held(c,'add'),HELD_PLAIN:lambda c:held(c,'remove')}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=3 if cid==SPELL else 1,on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,HUSH,PIRATIZE,REMOVE_PIRATE)else None,
            metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K693 deliberate original-draw/quote/choice rollback')))
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id);extra=()
        if e.kind=='card_drawn':
            if source is None or source.kind!=CardType.HERO_POWER or target is None or target.zone!=Zone.HAND:return()
            extra=(MoveCard(CardReference.capture(target),c.player_id,Zone.DECK,position='top',source_id=c.source_id),)
        elif e.kind=='cost_modified':
            if source is None or source.card_id!=FIZZLE:return()
        elif e.kind=='card_committed':
            if source is None or source.card_id!=KRAGG:return()
            original=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==PIRATE)
            extra=(Destroy(original,c.source_id),)
        elif e.kind=='minion_summoned':
            if target is None or target.card_id!=TREANT:return()
        elif source is None or source.card_id!=GORMOK:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('move','Move original',extra),
            ChoiceOption('fault','Fail after random work',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((DRAW_WATCH,'card_drawn'),(COST_WATCH,'cost_modified'),(COMMIT_WATCH,'card_committed'),
            (SUMMON_WATCH,'minion_summoned'),(DAMAGE_WATCH,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,triggers=(TriggerSpec(event,WATCH),),metadata=replace(metadata(collectible=False),tribes=())))
    r.validate();return r


class ClassicPowerPirateTargetTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(A,)*8,player=1,power=HP):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,deck=deck if p==player else(A,)*8,
            hero_power_card_id=power,mana=20,max_mana=20,mana_cap=20)for p in(1,2)),active_player=player,seed=693),fixture('writer'))
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def price(self,g,cid,p=1):return g.quote_cost(self.entity(g,cid,p).id).amount
    def power(self,g,p=1):g.apply(UseHeroPower(p,g.state.players[p].hero_power_ids[0]))
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def cenarius(self,g,branch,position=None):
        source=self.entity(g,CENARIUS).id;g.apply(PlayCard(1,source,position=position,branch_id=branch));return source
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)

    def test_full_source_roles_real_choice_rows_and_unchanged_life_tap(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),16)
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(fixture().card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(fixture().pool_card(cid))),row['pool_card_sha256'])
        self.assertEqual([b.id for b in fixture().card(CENARIUS).choose_one.branches],[native.BUFF_OPTION,native.SUMMON_OPTION])
        self.assertNotIn(native.BUFF_OPTION,fixture().cards);self.assertNotIn(HP,fixture().pool_cards)

    def test_finite_pirate_selector_keeps_old_serialized_fields_and_rejects_other_scope(self):
        self.assertEqual([f.name for f in fields(BoardMinionCostSpec)],['scope','profile_id'])
        self.assertEqual(BoardMinionCostSpec('friendly',native.PIRATE_PROFILE).tribes_any,('pirate',))
        self.assertEqual(BoardMinionCostSpec('friendly','cost.board-friendly-elementals-v1').tribes_any,('elemental',))
        for scope in('all','enemy'):
            with self.assertRaises(ValueError):BoardMinionCostSpec(scope,native.PIRATE_PROFILE)
        with self.assertRaises(ValueError):BoardMinionCostSpec('friendly','invented.pirates')

    def test_all_six_real_entries_pay_and_keep_actual_stats(self):
        for cid in(*native.ROOTS,TREANT):
            g=self.game((cid,));card=fixture().card(cid)
            source=self.cenarius(g,native.BUFF_OPTION)if cid==CENARIUS else self.play(g,cid)
            self.assertEqual(g.state.players[1].mana,20-card.cost)
            self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(card.attack,card.health))

    def test_wilfred_real_life_tap_prices_original_minion_spell_weapon_and_location_zero(self):
        for cid in(A,SPELL,WEAPON,LOC):
            g=self.game(board=(FIZZLE,),deck=(cid,));self.power(g)
            self.assertEqual(self.price(g,cid),0);self.assertEqual(g.state.players[1].mana,18);self.assertEqual(self.hero(g).health,28)
            row=g.state.draw_history[0];power=g.state.hero_power_history[0];self.assertEqual(row.source_id,power.source_id)

    def test_wilfred_each_draw_of_one_accepted_power_gets_its_own_original_zero_price(self):
        g=self.game(board=(FIZZLE,),deck=(A,SPELL),power=DOUBLE_HP);self.power(g)
        self.assertEqual([g.quote_cost(eid).amount for eid in g.state.players[1].hand],[0,0]);self.assertEqual(len(g.state.hero_power_history),1)
        self.assertEqual(len(g.state.draw_history),2)

    def test_wilfred_spell_and_natural_draws_and_drawing_wilfred_itself_do_not_gain_zero(self):
        g=self.game((DRAW,),board=(FIZZLE,));self.play(g,DRAW);self.assertEqual(self.price(g,A),3)
        g=self.game(board=(FIZZLE,));self.end(g);self.end(g);self.assertEqual(self.price(g,A),3)
        g=self.game(deck=(FIZZLE,));self.power(g);self.assertEqual(self.price(g,FIZZLE),6)

    def test_wilfred_silence_or_retirement_prevents_future_discount_but_old_discount_persists(self):
        g=self.game((KILL,),board=(FIZZLE,));self.power(g);self.play(g,KILL,self.unit(g,FIZZLE).id)
        self.assertEqual(self.price(g,A),0);mana=g.state.players[1].mana;self.play(g,A);self.assertEqual(g.state.players[1].mana,mana)
        g=self.game((HUSH,),board=(FIZZLE,));self.play(g,HUSH,self.unit(g,FIZZLE).id);self.power(g);self.assertEqual(self.price(g,A),3)

    def test_wilfred_fatigue_and_burn_are_not_original_hand_arrivals(self):
        g=self.game(board=(FIZZLE,),deck=());self.power(g);self.assertEqual(self.hero(g).health,27)
        self.assertFalse(any(e.kind=='cost_modified'for e in g.events))
        g=self.game((A,)*10,board=(FIZZLE,));self.power(g);self.assertEqual(g.state.draw_history[0].outcome,'burned')
        self.assertFalse(any(e.kind=='cost_modified'for e in g.events))

    def test_wilfred_only_current_controller_power_draw_and_second_seat_are_supported(self):
        g=self.game(board=(),enemy=(FIZZLE,));self.power(g);self.assertEqual(self.price(g,A),3)
        g=self.game(board=(FIZZLE,),player=2);self.power(g,2);self.assertEqual(self.price(g,A,2),0);self.portable(g)

    def test_wilfred_earlier_draw_wait_moving_original_arrival_skips_stale_cost_grant(self):
        g=self.game((DRAW,),board=(DRAW_WATCH,FIZZLE),deck=(A,));self.power(g);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'move');self.finish(g);self.play(g,DRAW)
        self.assertEqual(self.price(g,A),3);self.assertEqual(len(g.state.hero_power_history),1);self.portable(g)

    def test_wilfred_cost_notification_wait_restores_actual_power_and_failure_without_repayment(self):
        g=self.game(board=(FIZZLE,COST_WATCH));self.power(g);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.price(g,A),0)
        self.assertEqual((g.state.players[1].mana,self.hero(g).health),(18,28));self.portable(g)

    def test_kragg_counts_current_friendly_pirates_all_tribes_and_not_enemy_or_other_minions(self):
        g=self.game((KRAGG,),board=(PIRATE,ALL,A),enemy=(PIRATE,));self.assertEqual(self.price(g,KRAGG),5)
        source=self.play(g,KRAGG);self.assertEqual(g.state.players[1].mana,15)
        g.apply(Attack(1,source,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,26)

    def test_kragg_current_tribe_gain_silence_and_all_tribe_exclusion_change_current_quote(self):
        g=self.game((KRAGG,PIRATIZE,HUSH),board=(A,));target=self.unit(g,A).id;self.play(g,PIRATIZE,target)
        self.assertEqual(self.price(g,KRAGG),6);self.play(g,HUSH,target);self.assertEqual(self.price(g,KRAGG),7)
        g=self.game((KRAGG,REMOVE_PIRATE),board=(ALL,));self.assertEqual(self.price(g,KRAGG),6)
        self.play(g,REMOVE_PIRATE,self.unit(g,ALL).id);self.assertEqual(self.price(g,KRAGG),7)

    def test_kragg_zero_floor_queries_are_pure_and_own_source_is_not_counted_before_payment(self):
        g=self.game((KRAGG,),board=(PIRATE,)*6);before=g.snapshot();self.assertEqual(self.price(g,KRAGG),1)
        self.assertEqual(g.snapshot(),before);self.play(g,KRAGG);self.assertEqual(g.state.players[1].mana,19)
        g=self.game((KRAGG,),board=(PIRATE,)*7);before=g.snapshot();self.assertEqual(self.price(g,KRAGG),0)
        with self.assertRaises(IllegalAction):self.play(g,KRAGG)
        self.assertEqual(g.snapshot(),before)

    def test_kragg_paid_original_pirate_fact_survives_source_death_during_commit_wait(self):
        g=self.game((KRAGG,),board=(PIRATE,COMMIT_WATCH));self.play(g,KRAGG);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'move');self.assertEqual(g.state.players[1].mana,14)
        self.assertEqual(self.unit(g,KRAGG).attack,4);self.portable(g)

    def test_rend_without_held_dragon_has_no_arrow_and_with_dragon_requires_available_legendary(self):
        g=self.game((REND,),enemy=(LEGEND,));self.play(g,REND);self.assertEqual(len(g.state.players[2].board),1)
        g=self.game((REND,DRAGON),enemy=(LEGEND,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,REND)
        self.assertEqual(g.snapshot(),before);target=self.unit(g,LEGEND,2).id;self.play(g,REND,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_rend_can_destroy_own_legendary_and_rejects_nonlegendary_and_heroes(self):
        g=self.game((REND,DRAGON),board=(LEGEND,),enemy=(A,));before=g.snapshot()
        for target in(self.unit(g,A,2).id,self.hero(g,2).id):
            with self.assertRaises(IllegalAction):self.play(g,REND,target)
            self.assertEqual(g.snapshot(),before)
        target=self.unit(g,LEGEND).id;self.play(g,REND,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)

    def test_rend_current_hand_tribes_enable_and_remove_condition_without_changing_printed_cards(self):
        g=self.game((REND,A,HELD_DRAGON,HELD_PLAIN),enemy=(LEGEND,));source=self.entity(g,REND).id
        self.assertEqual(g.legal_targets(source),());self.play(g,HELD_DRAGON);self.assertEqual(g.legal_targets(source),(self.unit(g,LEGEND,2).id,))
        self.play(g,HELD_PLAIN);self.assertEqual(g.legal_targets(source),());self.play(g,REND)

    def test_rend_all_tribe_hand_and_hidden_opponent_hand_do_not_change_public_target_legality(self):
        targets=[];views=[]
        for hidden in(A,DRAGON):
            g=self.game((REND,ALL),enemy=(LEGEND,),enemy_hand=(hidden,));targets.append(g.legal_targets(self.entity(g,REND).id))
            views.append(g.for_player(1).observe()['observation'])
        self.assertEqual(targets[0],targets[1]);self.assertEqual(views[0],views[1])

    def test_gormok_three_other_minions_is_inactive_and_four_is_required_not_counting_self(self):
        g=self.game((GORMOK,),board=(A,)*3);self.play(g,GORMOK);self.assertEqual(self.hero(g,2).health,30)
        g=self.game((GORMOK,),board=(A,)*4);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,GORMOK)
        self.assertEqual(g.snapshot(),before);self.play(g,GORMOK,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,26)

    def test_gormok_counts_dormant_ordinary_minions_but_not_locations_and_uses_nonspell_damage(self):
        g=self.game((GORMOK,),board=(A,A,A,DORMANT));self.play(g,GORMOK,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,26)
        g=self.game((GORMOK,),board=(A,A,A,LOC));self.play(g,GORMOK);self.assertEqual(self.hero(g,2).health,30)
        g=self.game((GORMOK,),board=(A,A,A,POWER));self.play(g,GORMOK,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,26)

    def test_gormok_damage_wait_has_actual_four_damage_and_independent_restore_rollback(self):
        g=self.game((GORMOK,),board=(A,A,A,DAMAGE_WATCH));self.play(g,GORMOK,self.hero(g,2).id);before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.hero(g,2).health,26);self.portable(g)

    def test_cenarius_buff_branch_changes_only_other_live_friendly_minions(self):
        g=self.game((CENARIUS,),board=(A,DORMANT),enemy=(A,));source=self.cenarius(g,native.BUFF_OPTION)
        self.assertEqual((self.unit(g,A).attack,self.unit(g,A).health),(4,12))
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,8));self.assertEqual(self.unit(g,A,2).attack,2)
        self.assertEqual(self.unit(g,DORMANT).health,10)

    def test_cenarius_summons_real_two_taunt_treants_on_captured_source_flanks(self):
        g=self.game((CENARIUS,),board=(A,LEGEND));source=self.cenarius(g,native.SUMMON_OPTION,1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[A,TREANT,CENARIUS,TREANT,LEGEND])
        for eid in g.state.players[1].board:
            e=g.state.entities[eid]
            if e.card_id==TREANT:self.assertEqual((e.attack,e.health),(2,2));self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertEqual(g.state.players[1].mana,12);self.assertEqual(g.state.entities[source].card_id,CENARIUS)

    def test_cenarius_normal_capacity_allows_one_or_zero_treants_without_rejecting_root(self):
        for count,expected in((5,1),(6,0)):
            g=self.game((CENARIUS,),board=(A,)*count);self.cenarius(g,native.SUMMON_OPTION)
            self.assertEqual(sum(g.state.entities[i].card_id==TREANT for i in g.state.players[1].board),expected)
            self.assertEqual(g.state.players[1].mana,12)

    def test_cenarius_real_fandral_combined_branch_summons_then_freshly_buffs_four_four(self):
        g=self.game((CENARIUS,),board=(FANDRAL,A));source=self.cenarius(g,'both')
        treants=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==TREANT]
        self.assertEqual([(e.attack,e.health)for e in treants],[(4,4),(4,4)]);self.assertEqual(self.unit(g,A).attack,4)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,8));self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_cenarius_rejects_missing_invalid_or_unavailable_combined_branch_atomically(self):
        for branch in(None,'invented','both'):
            g=self.game((CENARIUS,));before=g.snapshot()
            with self.assertRaises(IllegalAction):self.cenarius(g,branch)
            self.assertEqual(g.snapshot(),before)

    def test_cenarius_combined_first_summon_wait_restores_tail_and_late_buff_without_duplicate(self):
        g=self.game((CENARIUS,),board=(FANDRAL,SUMMON_WATCH));self.cenarius(g,'both');before=g.snapshot();g=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g)
        treants=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==TREANT]
        self.assertEqual([(e.attack,e.health)for e in treants],[(4,4),(4,4)]);self.portable(g)

    def test_standard_host_actual_life_tap_draw_discount_and_current_pirate_payment_restore(self):
        self.mode='host';h=host('writer')
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_07',board=(FIZZLE,KRAGG),hand=(KRAGG,),
            deck=('CORE_CS2_182',)*8,hero_power_card_id=HP,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8)),generation_context=h.context,seed=693),h.registry)
        self.power(g);self.assertEqual(self.price(g,'CORE_CS2_182'),0);self.assertEqual(self.price(g,KRAGG),6)
        source=self.play(g,KRAGG);g.apply(Attack(1,source,self.hero(g,2).id))
        self.assertEqual(g.state.players[1].mana,12);self.assertEqual(self.hero(g).health,28);self.assertEqual(self.hero(g,2).health,26);self.portable(g)
