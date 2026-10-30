"""Real entries and original health/combat/stat/weapon boundaries."""
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_stat_trigger_return_consumers as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,Destroy,Draw,GainArmor,GrantKeyword,Heal,InvokeBehavior,ModifyWeapon,
    RandomDamage,RequestChoice,Silence)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,DamageKind,HealingKind,Keyword,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import Registry
from hs_sim.engine.return_followups import ReturnCapturedMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost,MoveCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

GUN,GUFF,ROKARA,CROWLEY,BOOGEY,GLASS,BOLVAR,BAROV,TARIM,KELE,GRUMBLE,ASH=native.ROOTS
P='k704.';A=P+'plain';SMALL=P+'small';TANK=P+'tank';DORMANT=P+'dormant';POWER=P+'power';SHIELD=P+'shield';LIFE=P+'life';BC=P+'battlecry';TWO=P+'two'
NATURE=P+'nature';ARCANE=P+'arcane';SPELL_TWO=P+'two_spell';HEAL=P+'heal';ZERO=P+'zero';LETHAL=P+'lethal'
KILL=P+'kill';HUSH=P+'hush';BUFF=P+'buff';GIVE_SHIELD=P+'give_shield';LOWER=P+'lower';AUTO=P+'automatic';DRAW=P+'draw';COPY=P+'copy'
W1=P+'hidden_weapon';W2=P+'equipped_weapon';QUEUE=P+'queue_weapon';BAD=P+'bad_weapon';BACK=P+'back';FAIL=P+'fail'
WATCH_DAMAGE=P+'damage_watch';WATCH_ATTACK=P+'attack_watch';WATCH_STATS=P+'stats_watch';WATCH_RETURN=P+'return_watch';WATCH_WEAPON=P+'weapon_watch'
HELPERS=(A,SMALL,TANK,DORMANT,POWER,SHIELD,LIFE,BC,TWO,NATURE,ARCANE,SPELL_TWO,HEAL,ZERO,LETHAL,KILL,HUSH,BUFF,GIVE_SHIELD,LOWER,AUTO,DRAW,COPY,W1,W2,QUEUE,BAD,WATCH_DAMAGE,WATCH_ATTACK,WATCH_STATS,WATCH_RETURN,WATCH_WEAPON)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(CardClass.MAGE,collectible=False)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,5),))
    for cid,attack,hp,cost in((A,2,12,3),(SMALL,1,1,1),(TANK,20,30,1),(DORMANT,2,12,3),(POWER,1,8,1),
            (SHIELD,1,8,3),(LIFE,1,8,3),(BC,2,12,6),(TWO,2,4,2),(WATCH_WEAPON,0,15,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=hp,metadata=meta,
            battlecry=P+'bc'if cid==BC else None,dormant_turns=2 if cid==DORMANT else 0,spell_damage=3 if cid==POWER else 0,
            keywords=(Keyword.DIVINE_SHIELD,)if cid==SHIELD else(Keyword.LIFESTEAL,)if cid==LIFE else(),
            triggers=(TriggerSpec('stored_card_buffed',P+'wait'),TriggerSpec('weapon_changed',P+'wait'))if cid==WATCH_WEAPON else()))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K704 intentional original continuation failure')))
    def waiting(c):
        source=c.state.entities.get(c.event.source_id)
        if c.event.kind=='damage_dealt' and(source is None or source.card_id not in(GUN,BAROV)):return()
        if c.event.kind=='stats_changed' and(source is None or source.card_id not in(BAROV,TARIM)):return()
        if c.event.kind in('stored_card_buffed','weapon_changed')and(source is None or source.card_id!=ASH):return()
        extra=()
        if c.event.kind=='card_returned':
            targets=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==BC]
            if targets:extra=(ChoiceOption('remove','Remove later original',(Destroy(targets[-1],c.source_id),)),)
        if c.event.kind=='stats_changed':
            targets=[i for i in c.state.players[2].board if c.state.entities[i].card_id==A]
            if targets:extra=(ChoiceOption('remove','Return later original',(
                ReturnCapturedMinion(MinionReference.capture(c.state.entities[targets[-1]]),c.source_id),)),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Failure',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),*extra),c.source_id),)
    r.register_behavior(P+'wait',waiting)
    def queued(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==W1);ref=CardReference.capture(e)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Failure',(
                RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),
            ChoiceOption('move','Move original',(MoveCard(ref,c.player_id,Zone.DECK,source_id=c.source_id),)),
            ChoiceOption('reenter','Leave and reenter original',(
                MoveCard(ref,c.player_id,Zone.DECK,source_id=c.source_id),InvokeBehavior(BACK,c.source_id,c.player_id,e.id)))),c.source_id),
            ModifyWeapon(e.id,1,1,c.source_id,stored_card=ref))
    r.register_behavior(BACK,lambda c:(MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.HAND,source_id=c.source_id),))
    def copied(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==W1)
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,e),c.player_id,mode='current',source_id=c.source_id),)
    def bad(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==A)
        return(ModifyWeapon(e.id,1,1,c.source_id,stored_card=CardReference.capture(e)),)
    scripts={NATURE:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        ARCANE:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        SPELL_TWO:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        HEAL:lambda c:(Heal(c.target_id,4,c.source_id,HealingKind.SPELL),),ZERO:lambda c:(Damage(c.target_id,0,c.source_id),),
        LETHAL:lambda c:(Damage(c.target_id,8,c.source_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),BUFF:lambda c:(Buff(c.target_id,3,4,c.source_id),),
        GIVE_SHIELD:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        LOWER:lambda c:tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=1),c.source_id)
            for i in c.state.players[c.player_id].deck),
        AUTO:lambda c:(CastSpell(c.player_id,NATURE,c.source_id,c.state.players[2].hero_id,targeting='explicit'),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),COPY:copied,QUEUE:queued,BAD:bad}
    no_target=(LOWER,AUTO,DRAW,COPY,QUEUE,BAD)
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=2 if cid==SPELL_TWO else 0,
            on_play=cid,metadata=meta,spell_school=SpellSchool.NATURE if cid==NATURE else SpellSchool.HOLY if cid==HEAL else SpellSchool.ARCANE,
            targeting=None if cid in no_target else TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,attack,durability,cost in((W1,2,3,2),(W2,1,4,3)):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,cost=cost,attack=attack,durability=durability,metadata=meta))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,event in((WATCH_DAMAGE,'damage_dealt'),(WATCH_ATTACK,'attack_finished'),(WATCH_STATS,'stats_changed'),(WATCH_RETURN,'card_returned')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,P+'wait'),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k704-original-stat-triggers-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('HERO_08','HERO_08bp',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_stat_trigger_return_consumers(r);r.validate();return r


class PastStatTriggerReturnTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*12,enemy_hand=(),watch=None,weapon=None,real_host=False,seed=704):
        self.mode='host'if real_host else'small';h=host()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30,
            hero_power_card_id='HERO_08bp',weapon_card_id=watch or weapon),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*12,mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp')),
            seed=seed,generation_context=h.context if real_host else None),h.registry if real_host else fixture())
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def weapon(self,g):return g.state.entities[g.state.players[1].weapon_id]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_all_twelve_complete_faces_and_full_source_roles(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),26);self.assertEqual(d['dependencies'],[])
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(fixture().card(cid),native.make_definition(row['record']))
            self.assertEqual(fixture().pool_card(cid),PoolCard.from_definition(fixture().card(cid)))

    def test_all_twelve_have_real_paid_hand_entries(self):
        for cid in native.ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(A,),enemy=(A,));self.play(g,cid)
                self.assertEqual(g.state.players[1].mana,30-fixture().card(cid).cost)
                self.assertEqual(sum(x.card_id==cid and x.player_id==1 for x in g.state.play_history),1)

    def test_gunspire_printed_no_attack_and_positive_damage_without_spell_bonus(self):
        g=self.game((NATURE,),board=(GUN,POWER));before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,self.unit(g,GUN).id,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),before);self.play(g,NATURE,self.unit(g,GUN).id)
        self.assertEqual(self.hero(g,2).health,27)

    def test_gunspire_zero_prevented_damage_and_healing_do_not_fire(self):
        g=self.game((ZERO,GIVE_SHIELD,NATURE,HEAL),board=(GUN,));source=self.unit(g,GUN).id;before=g.snapshot()['rng_state']
        self.play(g,ZERO,source);self.play(g,GIVE_SHIELD,source);self.play(g,NATURE,source);self.play(g,HEAL,source)
        self.assertEqual(self.hero(g,2).health,30);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_gunspire_original_lethal_damage_still_resolves_accepted_reaction(self):
        g=self.game((LETHAL,),board=(GUN,));self.play(g,LETHAL,self.unit(g,GUN).id)
        self.assertNotIn(GUN,self.board(g));self.assertEqual(self.hero(g,2).health,27)

    def test_gunspire_damage_wait_restores_replays_and_rolls_back_rng_failure(self):
        g=self.game((NATURE,),board=(GUN,),watch=WATCH_DAMAGE);self.play(g,NATURE,self.unit(g,GUN).id)
        self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.hero(g,2).health,27);self.portable(g)

    def test_guff_successful_nature_only_buffs_other_friendly_original(self):
        g=self.game((ARCANE,NATURE),board=(GUFF,A),enemy=(A,));self.play(g,ARCANE,self.hero(g,2).id)
        self.assertEqual(self.unit(g,A).attack,2);self.play(g,NATURE,self.hero(g,2).id)
        self.assertEqual((self.unit(g,A).attack,self.unit(g,A).health),(4,14));self.assertEqual(self.unit(g,GUFF).attack,2)
        self.assertEqual(self.unit(g,A,2).attack,2)

    def test_guff_observes_actual_automatic_nature_cast(self):
        g=self.game((AUTO,),board=(GUFF,A));self.play(g,AUTO)
        self.assertEqual(self.unit(g,A).attack,4);self.assertTrue(any(x.card_id==NATURE and x.origin=='effect'for x in g.state.cast_history))

    def test_guff_empty_group_and_silenced_source_neither_buff_nor_sample(self):
        g=self.game((NATURE,),board=(GUFF,));before=g.snapshot()['rng_state'];self.play(g,NATURE,self.hero(g,2).id)
        self.assertEqual(g.snapshot()['rng_state'],before)
        g=self.game((HUSH,NATURE),board=(GUFF,A));self.play(g,HUSH,self.unit(g,GUFF).id);self.play(g,NATURE,self.hero(g,2).id)
        self.assertEqual(self.unit(g,A).attack,2)

    def test_rokara_rewards_other_surviving_original_and_her_own_rush_attack(self):
        g=self.game((ROKARA,),board=(A,),enemy=(A,));source=self.play(g,ROKARA);target=self.unit(g,A,2).id
        g.apply(Attack(1,self.unit(g,A).id,target));self.assertEqual((self.unit(g,A).attack,self.unit(g,A).health),(3,11))
        g.apply(Attack(1,source,target));self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,2))

    def test_rokara_excludes_dead_attacker_enemy_attack_and_hero(self):
        g=self.game((ROKARA,),board=(A,),enemy=(TANK,));self.play(g,ROKARA);g.apply(Attack(1,self.unit(g,A).id,self.unit(g,TANK,2).id))
        self.assertNotIn(A,self.board(g));self.assertEqual(self.unit(g,ROKARA).attack,2)
        g=self.game(board=(ROKARA,A),enemy=(SMALL,),weapon=W1);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.assertEqual(self.unit(g,ROKARA).attack,2);g.apply(EndTurn(1));g.apply(Attack(2,self.unit(g,SMALL,2).id,self.unit(g,A).id))
        self.assertEqual(self.unit(g,A).attack,2)

    def test_crowley_and_boogey_require_actual_own_combat_kill_and_survival(self):
        for cid in(CROWLEY,BOOGEY):
            with self.subTest(cid=cid):
                g=self.game(board=(cid,),enemy=(SMALL,));g.apply(Attack(1,self.unit(g,cid).id,self.unit(g,SMALL,2).id))
                e=self.unit(g,cid);d=fixture().card(cid);self.assertEqual((e.attack,e.health),(d.attack+2,d.health+1))

    def test_kill_growth_does_not_count_surviving_target_later_destroy_or_defending(self):
        g=self.game((KILL,),board=(CROWLEY,),enemy=(A,));target=self.unit(g,A,2).id
        g.apply(Attack(1,self.unit(g,CROWLEY).id,target));self.play(g,KILL,target);self.assertEqual(self.unit(g,CROWLEY).attack,4)
        g=self.game(board=(CROWLEY,),enemy=(SMALL,));g.apply(EndTurn(1));g.apply(Attack(2,self.unit(g,SMALL,2).id,self.unit(g,CROWLEY).id))
        self.assertEqual(self.unit(g,CROWLEY).attack,4)

    def test_real_attack_growth_wait_keeps_original_combat_and_replays_once(self):
        g=self.game(board=(CROWLEY,ROKARA),enemy=(SMALL,),watch=WATCH_ATTACK)
        g.apply(Attack(1,self.unit(g,CROWLEY).id,self.unit(g,SMALL,2).id));self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.unit(g,CROWLEY).attack,7);self.portable(g)

    def test_glass_real_own_healing_of_enemy_restores_shield(self):
        g=self.game((NATURE,NATURE,HEAL),board=(GLASS,),enemy=(A,));source=self.unit(g,GLASS).id
        self.play(g,NATURE,source);self.play(g,NATURE,self.unit(g,A,2).id);self.play(g,HEAL,self.unit(g,A,2).id)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)

    def test_glass_overheal_and_other_player_actual_healing_do_not_restore_shield(self):
        g=self.game((NATURE,NATURE,HEAL),board=(GLASS,),enemy=(A,),enemy_hand=(HEAL,));source=self.unit(g,GLASS).id
        self.play(g,NATURE,source);self.play(g,HEAL,self.hero(g).id);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        self.play(g,NATURE,self.unit(g,A,2).id);g.apply(EndTurn(1));self.play(g,HEAL,self.unit(g,A,2).id,2)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)

    def test_glass_positive_lifesteal_is_real_attributed_healing(self):
        g=self.game((NATURE,NATURE),board=(GLASS,LIFE),enemy=(A,));source=self.unit(g,GLASS).id
        self.play(g,NATURE,source);self.play(g,NATURE,self.hero(g).id);g.apply(Attack(1,self.unit(g,LIFE).id,self.unit(g,A,2).id))
        self.assertEqual(self.hero(g).health,30);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)

    def test_bolvar_real_friendly_shield_loss_includes_self_but_not_enemy(self):
        g=self.game((NATURE,)*3,board=(BOLVAR,SHIELD),enemy=(SHIELD,));source=self.unit(g,BOLVAR).id
        self.play(g,NATURE,self.unit(g,SHIELD,2).id);self.assertEqual(g.state.entities[source].attack,1)
        self.play(g,NATURE,self.unit(g,SHIELD).id);self.assertEqual(g.state.entities[source].attack,3)
        self.play(g,NATURE,source);self.assertEqual(g.state.entities[source].attack,5)

    def test_barov_sets_original_other_health_then_real_deathrattle_clears_them(self):
        g=self.game((BAROV,KILL),board=(A,DORMANT),enemy=(A,));source=self.play(g,BAROV)
        self.assertEqual((self.unit(g,A).attack,self.unit(g,A).health),(2,1));self.assertEqual(self.unit(g,A,2).health,1)
        self.assertEqual(self.unit(g,DORMANT).health,12);self.assertEqual(g.state.entities[source].health,2)
        self.play(g,KILL,source);self.assertEqual(self.board(g),[DORMANT]);self.assertEqual(self.board(g,2),[])

    def test_barov_death_damage_has_no_spell_bonus_and_keeps_shield_prevention(self):
        g=self.game((KILL,),board=(BAROV,POWER),enemy=(SHIELD,));source=self.unit(g,BAROV).id;self.play(g,KILL,source)
        self.assertEqual(self.unit(g,POWER).health,7);self.assertEqual(self.unit(g,SHIELD,2).health,8)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.unit(g,SHIELD,2).keywords)

    def test_tarim_sets_both_sides_other_originals_and_excludes_dormancy(self):
        g=self.game((BUFF,TARIM),board=(A,DORMANT),enemy=(TANK,));self.play(g,BUFF,self.unit(g,A).id);self.play(g,TARIM)
        self.assertEqual((self.unit(g,A).attack,self.unit(g,A).health),(3,3));self.assertEqual(self.unit(g,TANK,2).attack,3)
        self.assertEqual(self.unit(g,DORMANT).health,12);self.assertEqual(self.unit(g,TARIM).health,7)

    def test_tarim_wait_skips_later_original_after_it_returns_to_hand(self):
        g=self.game((TARIM,),board=(A,),enemy=(A,),watch=WATCH_STATS);self.play(g,TARIM);self.portable(g);self.fault(g)
        self.choose(g,'remove');self.finish(g);self.assertEqual(self.entity(g,A,2).health,12);self.portable(g)

    def test_keleseth_any_current_two_cost_type_prevents_deck_buff(self):
        for cid in(TWO,SPELL_TWO,W1):
            with self.subTest(cid=cid):
                g=self.game((KELE,),deck=(A,cid));self.play(g,KELE);self.assertEqual(self.entity(g,A,zone='deck').attack,2)

    def test_keleseth_buffs_original_deck_minions_not_held_board_or_spells(self):
        g=self.game((KELE,A),board=(A,),deck=(A,ARCANE));self.play(g,KELE)
        self.assertEqual((self.entity(g,A,zone='deck').attack,self.entity(g,A,zone='deck').health),(3,13))
        self.assertEqual(self.entity(g,A).attack,2);self.assertEqual(self.unit(g,A).attack,2);self.assertEqual(self.unit(g,KELE).attack,2)

    def test_keleseth_uses_actual_stored_local_cost_after_physical_modification(self):
        g=self.game((LOWER,KELE),deck=(A,TWO));self.play(g,LOWER);self.play(g,KELE)
        self.assertEqual(self.entity(g,A,zone='deck').attack,3);self.assertEqual(self.entity(g,TWO,zone='deck').attack,3)

    def test_grumble_returns_originals_resets_them_and_retains_one_cost_next_turn(self):
        g=self.game((BUFF,GRUMBLE),board=(A,BC,DORMANT));original=self.unit(g,A).id;self.play(g,BUFF,original);self.play(g,GRUMBLE)
        self.assertEqual(self.hand(g),[A,BC]);self.assertEqual(self.entity(g,A).id,original)
        self.assertEqual((self.entity(g,A).attack,self.entity(g,A).health,local_cost(self.entity(g,A))[0]),(2,12,1))
        self.assertEqual(self.hero(g).armor,0);g.apply(EndTurn(1));self.assertEqual(local_cost(self.entity(g,BC))[0],1)

    def test_grumble_full_hand_uses_original_return_failure_death(self):
        g=self.game((GRUMBLE,)+(A,)*9,board=(A,BC));original=self.unit(g,BC).id;self.play(g,GRUMBLE)
        self.assertEqual(len(self.hand(g)),10);self.assertTrue(any(x.entity_id==original for x in g.state.death_history))
        self.assertEqual(self.board(g),[GRUMBLE])

    def test_grumble_return_wait_keeps_prices_and_frozen_original_group(self):
        g=self.game((GRUMBLE,),board=(A,BC),watch=WATCH_RETURN);self.play(g,GRUMBLE)
        self.assertEqual(local_cost(self.entity(g,A))[0],1);self.portable(g);self.fault(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(self.hand(g),[A]);self.portable(g)

    def test_ashvane_grows_every_original_physical_weapon_in_three_zones(self):
        g=self.game((ASH,W1,A),board=(A,),deck=(W1,SPELL_TWO),weapon=W2);self.play(g,ASH)
        for e in(self.entity(g,W1),self.entity(g,W1,zone='deck')):self.assertEqual((e.attack,e.durability),(3,4))
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(2,5));self.assertEqual(self.hero(g).attack,2)
        self.assertEqual(self.entity(g,A).attack,2);self.assertEqual(self.unit(g,A).attack,2)

    def test_ashvane_stored_material_survives_copy_draw_equip_and_real_weapon_wear(self):
        g=self.game((ASH,W1,COPY,DRAW),deck=(W1,));self.play(g,ASH);self.play(g,COPY);self.play(g,DRAW)
        self.assertEqual(self.hand(g),[W1,W1,W1])
        for i in g.state.players[1].hand:self.assertEqual((g.state.entities[i].attack,g.state.entities[i].durability),(3,4))
        self.play(g,W1);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id));self.assertEqual(self.weapon(g).durability,3)
        self.assertEqual(self.hero(g,2).health,27);self.portable(g)

    def test_ashvane_waiting_preserves_hidden_changes_and_information_boundaries(self):
        g=self.game((ASH,W1),board=(WATCH_WEAPON,),deck=(W1,),weapon=W2);self.play(g,ASH);self.portable(g);self.fault(g);self.finish(g)
        own=json.dumps(g.player_events(1));other=json.dumps(g.player_events(2))+json.dumps(g.for_player(2).observe())
        self.assertIn('stored_card_buffed',own);self.assertNotIn('stored_card_buffed',other);self.assertNotIn(W1,other)
        self.assertEqual(self.entity(g,W1).durability,4);self.assertEqual(self.entity(g,W1,zone='deck').durability,4);self.portable(g)

    def test_queued_stored_weapon_request_restores_and_skips_moved_or_reentered_original(self):
        for option,zone in(('move','deck'),('reenter','hand')):
            with self.subTest(option=option):
                g=self.game((QUEUE,W1));self.play(g,QUEUE);restored=self.portable(g);self.fault(g)
                self.choose(g,option);self.choose(restored,option);self.assertEqual(g.snapshot(),restored.snapshot())
                e=self.entity(g,W1,zone=zone);self.assertEqual((e.attack,e.durability),(2,3))

    def test_stored_weapon_wrong_original_kind_is_atomic_resolution_failure(self):
        g=self.game((BAD,A));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,BAD)
        self.assertEqual(g.snapshot(),before)

    def test_stored_weapon_declaration_rejects_forged_identity_and_negative_scope(self):
        ref=CardReference(3,1,Zone.HAND,W1,0)
        for create in(lambda:ModifyWeapon(4,1,1,stored_card=ref),lambda:ModifyWeapon(3,-1,1,stored_card=ref),
                lambda:ModifyWeapon(3,1,-1,stored_card=ref),lambda:ModifyWeapon(True,1,1,stored_card=ref),lambda:ModifyWeapon(3,1,1,stored_card='forged')):
            with self.subTest(create=create),self.assertRaises(ValueError):create()

    def test_standard_host_real_health_combat_and_three_zone_weapon_entries(self):
        g=self.game((ASH,W1),deck=(W1,),weapon=W2,real_host=True);self.play(g,ASH)
        self.assertEqual(self.entity(g,W1).durability,4);self.assertEqual(self.weapon(g).durability,5)
        g=self.game((CROWLEY,),enemy=(SMALL,),real_host=True);source=self.play(g,CROWLEY)
        g.apply(Attack(1,source,self.unit(g,SMALL,2).id));self.assertEqual(g.state.entities[source].attack,6)
