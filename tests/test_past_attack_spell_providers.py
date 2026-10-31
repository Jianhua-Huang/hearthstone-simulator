"""Real combat, spell providers, persistent programs and physical stored grants."""
from dataclasses import replace
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_attack_spell_providers as native
from hs_sim.engine import Attack,CastSpell,EndTurn,Game,PlayCard,PlayerSetup,Scenario
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,Draw,
    ForceAttack,GainArmor,GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.model import (AbilityInstance,BoardPresenceReference,CardDefinition,CardType,DamageKind,Keyword,
    KeywordAuraSpec,PlayerAuraSpec,SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolQuery
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

SLATE,KREE,REAPER,NORALIA,RISA,KNUCKLES,STONE,LOTH,SARUUN,HALDURON=native.ROOTS
RECRUIT=native.EXISTING[0];MISSILES='EX1_277'
P='k728.'
A,TOTEM,ELEMENTAL,ALL,MECH,MAGNET,STRONG,SHIELD,SLEEP=(P+x for x in('a','totem','elemental','all','mech','magnet','strong','shield','sleep'))
FIRE,ARCANE,FEL,ZERO,KILL,HUSH,RETURN,CONTROL,TO_TOTEM,TO_A,DRAW,ADD,COPY,SPELL_COPY,HURT,HEALING,FORCE,BARE,SUMMON=(P+x for x in
    ('fire','arcane','fel','zero','kill','hush','return','control','to_totem','to_a','draw','add','copy','spell_copy','hurt','healing','force','bare','summon'))
WATCH,FAIL,WEAPON=P+'watch',P+'fail',P+'weapon'
CTX=GenerationContext(P+'fixture','experimental')


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',host=False):
    h=full(role);r=h.registry if host else defaults()
    if not host:
        card=h.registry.card(MISSILES)
        if MISSILES not in r.cards:
            r.register_behavior(card.on_play,h.registry.behavior(card.on_play));r.register_card(card);r.register_pool_card(h.registry.pool_card(MISSILES))
        native.register_past_attack_spell_providers(r)
    meta=metadata(collectible=False,tribes=())
    for cid,cost,atk,hp,tribes,kw in((A,2,2,12,(),{}),(TOTEM,1,0,7,('totem',),{}),
            (ELEMENTAL,2,1,5,('elemental',),{}),(ALL,2,1,5,('all',),{}),(MECH,2,2,12,('mech',),{}),
            (MAGNET,2,1,4,('elemental','mech'),dict(keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',))),
            (STRONG,1,10,50,(),{}),(SHIELD,1,0,20,(),dict(keywords=(Keyword.DIVINE_SHIELD,))),
            (SLEEP,1,2,20,(),dict(dormant_turns=2))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,
            metadata=metadata(collectible=False,tribes=tribes),**kw));r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def summon(c):return(SummonByCard(c.player_id,(SummonEntryMaterial(RECRUIT),),SummonCause.capture(c)),)
    def force(c):
        enemy=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==A)
        return(ForceAttack(c.target_id,enemy.id),)
    bodies={FIRE:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        ARCANE:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),FEL:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        ZERO:lambda c:(GainArmor(c.player_id,1),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        RETURN:lambda c:(ReturnToHand(c.target_id),),CONTROL:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        TO_TOTEM:lambda c:(Transform(c.target_id,TOTEM),),TO_A:lambda c:(Transform(c.target_id,A),),
        DRAW:lambda c:(Draw(c.player_id,2,c.source_id),),ADD:lambda c:(AddToHand(c.player_id,ELEMENTAL,c.source_id),),
        COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
        SPELL_COPY:lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,source_id=c.source_id),),
        HURT:lambda c:(LoseHealth(c.state.players[c.player_id].hero_id,10,c.source_id),),
        HEALING:lambda c:(GrantKeyword(c.target_id,Keyword.LIFESTEAL,c.source_id),),FORCE:force,
        BARE:lambda c:(Damage(c.target_id,3,next(c.state.entities[i].id for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==KNUCKLES),DamageKind.COMBAT),),
        SUMMON:summon}
    targeted={FIRE,ARCANE,FEL,KILL,HUSH,RETURN,CONTROL,TO_TOTEM,TO_A,COPY,HEALING,FORCE,BARE}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        target=(TargetSpec(zones=(Zone.HAND,),kinds=(CardType.SPELL,),relation='friendly')if cid==SPELL_COPY else
            TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))if cid in targeted else None)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1 if cid in(FIRE,ARCANE,FEL)else 0,on_play=cid,
            spell_school={FIRE:SpellSchool.FIRE,ARCANE:SpellSchool.ARCANE,FEL:SpellSchool.FEL}.get(cid),targeting=target,metadata=meta))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=2,durability=20,metadata=meta))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K728 deliberate rollback')))
    def wait(c):
        e=c.event;s=c.state.entities.get(e.source_id);t=c.state.entities.get(e.target_id)
        relevant=(e.kind=='stored_spell_damage_granted'or e.kind=='player_effect_added'and s is not None and s.card_id in(STONE,LOTH)or
            e.kind=='minion_summoned'and t is not None and t.card_id==RECRUIT or
            e.kind=='health_resolved'and s is not None and s.card_id in(FIRE,ARCANE,FEL,MISSILES,KNUCKLES))
        if not relevant:return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),
            ChoiceOption('draw','Draw original physical cards',(Draw(c.player_id,2,c.source_id),)))
        sources=[c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in native.ROOTS]
        if sources:options+=(ChoiceOption('remove','Remove source',(Destroy(sources[0].id,c.source_id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait);r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,attack=2,durability=20,metadata=meta,
        triggers=tuple(TriggerSpec(kind,WATCH)for kind in('stored_spell_damage_granted','player_effect_added','minion_summoned','health_resolved'))))
    r.validate();return r,h.context if host else CTX


class AttackSpellProviderTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,host=False,watch=False,weapon=False):
        self.mode='host'if host else'small';r,ctx=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*12 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,weapon_card_id=WATCH if watch else WEAPON if weapon else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*12,mana=40,max_mana=40,mana_cap=40,armor=500)),
            seed=728,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def attack(self,g,cid,target,p=1):g.apply(Attack(p,self.unit(g,cid,p).id,target))
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:n+=1;self.assertLess(n,100);self.choose(g)
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)
    def grants(self,g,e):return[a for a in g.state.entities[e.id].abilities if a.kind=='spell_damage'and a.origin=='granted']

    def test_complete_twelve_rows_twenty_four_primary_faces_and_full_nine_Recruit_predicate(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),24);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['silver_hand_recruit_ids']),9);self.assertIn(RECRUIT,d['silver_hand_recruit_ids'])
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('reader')[0].card(cid))
        self.assertNotIn(RECRUIT,fixture()[0].pool_cards)

    def test_all_ten_actual_current_host_paid_entries_and_two_real_permanent_programs(self):
        for cid in native.ROOTS:
            g=self.game((cid,),host=True);sid=self.play(g,cid);self.assertTrue(g.state.play_history[0].completed)
            self.assertEqual(g.state.play_history[0].source_id,sid)
            if cid in(STONE,LOTH):self.assertEqual(len(g.state.players[1].player_effects),1)

    def test_Slate_real_spell_poison_kills_damaged_minion_but_Shield_and_hero_do_not_die(self):
        g=self.game((FIRE,FIRE,FIRE),board=(SLATE,),enemy=(A,SHIELD));aid=self.unit(g,A,2).id
        self.play(g,FIRE,aid);self.assertEqual(g.state.entities[aid].zone,Zone.GRAVEYARD)
        shield=self.unit(g,SHIELD,2).id;self.play(g,FIRE,shield);self.assertEqual(g.state.entities[shield].health,20)
        self.play(g,FIRE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,499)

    def test_Slate_silence_removes_live_spell_poison_without_removing_independent_keywords(self):
        g=self.game((FIRE,HUSH),board=(SLATE,),enemy=(A,));self.assertIn(Keyword.POISONOUS,self.entity(g,FIRE).keywords)
        self.play(g,HUSH,self.unit(g,SLATE).id);self.assertNotIn(Keyword.POISONOUS,self.entity(g,FIRE).keywords)
        self.play(g,FIRE,self.unit(g,A,2).id);self.assertEqual(self.unit(g,A,2).health,11)

    def test_Slate_actual_Missiles_freezes_whole_original_budget_and_keyword(self):
        g=self.game((MISSILES,),board=(SLATE,),enemy=(A,A,A));self.play(g,MISSILES)
        root=g.state.split_damage_history[0];self.assertTrue(root.completed);self.assertIn(Keyword.POISONOUS,root.quote.source_keywords)
        self.assertEqual(root.quote.budget,3);self.assertTrue(any(d.controller==2 for d in g.state.death_history));self.portable(g)

    def test_Slate_real_health_wait_restore_and_source_removal_keeps_original_packet(self):
        g=self.game((FIRE,),board=(SLATE,),enemy=(A,),watch=True);aid=self.unit(g,A,2).id;self.play(g,FIRE,aid)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(g.state.entities[aid].zone,Zone.GRAVEYARD);self.portable(g)

    def test_Kree_other_minion_attack_is_immune_but_Kree_itself_is_not(self):
        g=self.game(board=(KREE,A),enemy=(STRONG,));self.attack(g,A,self.unit(g,STRONG,2).id)
        self.assertEqual(self.unit(g,A).health,12);kid=self.unit(g,KREE).id;self.attack(g,KREE,self.unit(g,STRONG,2).id)
        self.assertEqual(g.state.entities[kid].zone,Zone.GRAVEYARD)

    def test_Kree_hero_attack_uses_scoped_immunity_and_normal_incoming_spell_does_not(self):
        g=self.game(board=(KREE,),enemy=(STRONG,),enemy_hand=(FIRE,),weapon=True)
        g.apply(Attack(1,self.hero(g).id,self.unit(g,STRONG,2).id));self.assertEqual(self.hero(g).armor,500)
        g.apply(EndTurn(1));self.play(g,FIRE,self.hero(g).id,2);self.assertEqual(self.hero(g).armor,499);self.portable(g)

    def test_Reaper_actual_cleave_hits_physical_neighbors_once_with_one_retaliation(self):
        g=self.game(board=(REAPER,),enemy=(A,A,A));enemy=list(g.state.players[2].board);self.attack(g,REAPER,enemy[1])
        self.assertEqual([g.state.entities[i].health for i in enemy],[6,6,6]);self.assertEqual(self.unit(g,REAPER).health,7)
        self.assertEqual(len(g.state.character_attack_history),1);self.portable(g)

    def test_Reaper_dormant_neighbor_is_not_a_bridge_and_silence_removes_cleave(self):
        g=self.game((HUSH,),board=(REAPER,),enemy=(A,SLEEP,A));enemy=list(g.state.players[2].board);self.attack(g,REAPER,enemy[0])
        self.assertEqual(g.state.entities[enemy[2]].health,12);self.assertEqual(g.state.entities[enemy[1]].health,20)
        g=self.game((HUSH,),board=(REAPER,),enemy=(A,A,A));self.play(g,HUSH,self.unit(g,REAPER).id)
        enemy=list(g.state.players[2].board);self.attack(g,REAPER,enemy[1]);self.assertEqual([g.state.entities[i].health for i in enemy],[12,6,12])

    def test_Noralia_real_Rush_cleave_and_actual_DR_uses_plain_enemy_two_damage(self):
        g=self.game((NORALIA,KILL),enemy=(TOTEM,TOTEM,TOTEM));sid=self.play(g,NORALIA);enemy=list(g.state.players[2].board)
        self.assertIn(Keyword.RUSH,g.state.entities[sid].keywords);amount=g.state.entities[sid].attack
        g.apply(Attack(1,sid,enemy[1]));self.assertEqual([g.state.entities[i].health for i in enemy],[7-amount]*3)
        self.play(g,KILL,sid);self.assertEqual([g.state.entities[i].health for i in enemy],[5-amount]*3);self.assertEqual(self.hero(g,2).armor,498)
        self.portable(g)

    def test_Knuckles_real_attack_adds_direct_hero_damage_without_an_extra_attack(self):
        g=self.game(board=(KNUCKLES,),enemy=(A,));self.attack(g,KNUCKLES,self.unit(g,A,2).id)
        self.assertEqual(self.hero(g,2).armor,497);self.assertEqual(self.unit(g,KNUCKLES).health,5)
        self.assertEqual(len(g.state.character_attack_history),1);self.portable(g)

    def test_Knuckles_lethal_retaliation_still_delivers_original_accepted_hero_hit(self):
        g=self.game(board=(KNUCKLES,),enemy=(STRONG,));sid=self.unit(g,KNUCKLES).id;self.attack(g,KNUCKLES,self.unit(g,STRONG,2).id)
        self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD);self.assertEqual(self.hero(g,2).armor,497);self.portable(g)

    def test_Knuckles_original_granted_Lifesteal_applies_to_both_hits_despite_lethal_retaliation(self):
        g=self.game((HURT,HEALING),board=(KNUCKLES,),enemy=(STRONG,));sid=self.unit(g,KNUCKLES).id
        self.play(g,HURT);self.play(g,HEALING,sid);self.attack(g,KNUCKLES,self.unit(g,STRONG,2).id)
        self.assertEqual(self.hero(g).health,26);self.assertEqual(self.hero(g,2).armor,497);self.portable(g)

    def test_Knuckles_hero_defender_reciprocal_hit_and_bare_COMBAT_do_not_duplicate(self):
        g=self.game(board=(KNUCKLES,));self.attack(g,KNUCKLES,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,497)
        g=self.game(board=(KNUCKLES,),enemy=(A,));g.apply(EndTurn(1));self.attack(g,A,self.unit(g,KNUCKLES).id,2)
        self.assertEqual(self.hero(g,2).armor,500)
        g=self.game((BARE,),board=(KNUCKLES,),enemy=(A,));self.play(g,BARE,self.unit(g,A,2).id);self.assertEqual(self.hero(g,2).armor,500)

    def test_Knuckles_opponent_forced_attack_keeps_original_controller_as_damage_owner(self):
        g=self.game(board=(KNUCKLES,),enemy=(A,),enemy_hand=(FORCE,));g.apply(EndTurn(1))
        self.play(g,FORCE,self.unit(g,KNUCKLES).id,2);self.assertEqual(self.hero(g,2).armor,497);self.assertEqual(self.hero(g).armor,500)

    def test_Knuckles_actual_health_wait_independent_restore_and_atomic_failure(self):
        g=self.game(board=(KNUCKLES,),enemy=(A,),watch=True);self.attack(g,KNUCKLES,self.unit(g,A,2).id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.finish(g)
        self.assertEqual(self.hero(g,2).armor,497);self.portable(g)

    def test_Risa_actual_own_hero_attack_returns_original_physical_minion_at_one_cost(self):
        g=self.game(board=(RISA,),enemy=(A,),weapon=True);sid=self.unit(g,RISA).id
        g.apply(Attack(1,self.hero(g).id,self.unit(g,A,2).id));self.assertIn(sid,g.state.players[1].hand)
        g.apply(PlayCard(1,sid));self.assertEqual(g.state.play_history[-1].cost,1);self.assertIn(Keyword.RUSH,g.state.entities[sid].keywords);self.portable(g)

    def test_Risa_minion_attack_and_silenced_source_do_not_return(self):
        g=self.game((HUSH,),board=(RISA,A),enemy=(A,),weapon=True);sid=self.unit(g,RISA).id
        self.attack(g,A,self.unit(g,A,2).id);self.assertIn(sid,g.state.players[1].board)
        self.play(g,HUSH,sid);g.apply(Attack(1,self.hero(g).id,self.unit(g,A,2).id));self.assertIn(sid,g.state.players[1].board)

    def test_Stonewright_current_and_future_Totems_all_type_and_transform_scope(self):
        g=self.game((STONE,TOTEM,TO_TOTEM,TO_A),board=(TOTEM,A,ALL),deck=(TOTEM,));self.play(g,STONE)
        self.assertEqual(self.unit(g,TOTEM).attack,2);self.assertEqual(self.unit(g,A).attack,2);self.assertEqual(self.unit(g,ALL).attack,3)
        self.assertEqual(self.entity(g,TOTEM).attack,0);self.assertEqual(g.state.entities[g.state.players[1].deck[0]].attack,0)
        sid=self.play(g,TOTEM);self.assertEqual(g.state.entities[sid].attack,2);aid=self.unit(g,A).id
        self.play(g,TO_TOTEM,aid);self.assertEqual(g.state.entities[aid].attack,2);self.play(g,TO_A,aid);self.assertEqual(g.state.entities[aid].attack,2)

    def test_Stonewright_program_stacks_survives_source_and_current_control_changes(self):
        g=self.game((STONE,STONE,KILL,CONTROL),board=(TOTEM,));sid=self.play(g,STONE);self.play(g,STONE)
        self.assertEqual(self.unit(g,TOTEM).attack,4);self.play(g,KILL,sid);tid=self.unit(g,TOTEM).id
        self.play(g,CONTROL,tid);self.assertEqual(g.state.entities[tid].attack,0);self.portable(g)

    def test_Stonewright_actual_program_install_wait_restore_keeps_original_owner(self):
        g=self.game((STONE,TOTEM),watch=True);self.play(g,STONE);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        sid=self.play(g,TOTEM);self.assertEqual(g.state.entities[sid].attack,2);self.portable(g)

    def test_Lothraxion_real_summons_receive_Shield_but_existing_or_enemy_Recruits_do_not(self):
        g=self.game((LOTH,SUMMON,RECRUIT),board=(RECRUIT,),enemy_hand=(SUMMON,));old=self.unit(g,RECRUIT).id;self.play(g,LOTH)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[old].keywords);self.play(g,SUMMON);sid=self.play(g,RECRUIT)
        self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[sid].keywords);g.apply(EndTurn(1));self.play(g,SUMMON,player=2)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.unit(g,RECRUIT,2).keywords);self.portable(g)

    def test_Lothraxion_source_death_and_two_programs_keep_one_ordinary_Shield(self):
        g=self.game((LOTH,LOTH,KILL,SUMMON),enemy_hand=(FIRE,FIRE));sid=self.play(g,LOTH);self.play(g,LOTH);self.play(g,KILL,sid);self.play(g,SUMMON)
        token=self.unit(g,RECRUIT).id;g.apply(EndTurn(1));self.play(g,FIRE,token,2)
        self.assertEqual(g.state.entities[token].zone,Zone.BOARD);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[token].keywords)
        self.play(g,FIRE,token,2);self.assertEqual(g.state.entities[token].zone,Zone.GRAVEYARD);self.portable(g)

    def test_Lothraxion_real_summon_wait_restore_and_source_removal(self):
        g=self.game((LOTH,SUMMON),watch=True);self.play(g,LOTH);self.finish(g);self.play(g,SUMMON)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertIn(Keyword.DIVINE_SHIELD,self.unit(g,RECRUIT).keywords);self.portable(g)

    def test_Saruun_only_current_original_deck_Elementals_receive_Fire_grant(self):
        g=self.game((SARUUN,ELEMENTAL),board=(ELEMENTAL,),deck=(ELEMENTAL,ALL,A,FIRE));self.play(g,SARUUN)
        cards=[g.state.entities[i]for i in g.state.players[1].deck]
        self.assertEqual([len(self.grants(g,e))for e in cards],[1,1,0,0]);self.assertEqual(self.grants(g,self.entity(g,ELEMENTAL)),[])
        self.assertEqual(self.grants(g,self.unit(g,ELEMENTAL)),[])

    def test_Saruun_draw_play_and_source_death_preserve_Fire_only_actual_damage(self):
        g=self.game((SARUUN,DRAW,KILL,FIRE,ARCANE),deck=(ELEMENTAL,A));sid=self.play(g,SARUUN);self.play(g,DRAW);self.play(g,ELEMENTAL);self.play(g,KILL,sid)
        self.play(g,FIRE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,498)
        self.play(g,ARCANE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,497);self.portable(g)

    def test_Saruun_current_copy_and_silence_use_original_removable_school_material(self):
        g=self.game((SARUUN,DRAW,COPY,HUSH,FIRE),deck=(ELEMENTAL,A));self.play(g,SARUUN);self.play(g,DRAW);sid=self.play(g,ELEMENTAL)
        self.play(g,COPY,sid);self.assertEqual(sum(len(self.grants(g,g.state.entities[i]))for i in g.state.players[1].board),2)
        self.play(g,HUSH,sid);self.play(g,FIRE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,498);self.portable(g)

    def test_Saruun_Fire_grant_survives_actual_magnetic_transfer_with_original_provenance(self):
        g=self.game((SARUUN,DRAW,FIRE),board=(MECH,),deck=(MAGNET,A));self.play(g,SARUUN);self.play(g,DRAW)
        mid=self.entity(g,MAGNET).id;host=self.unit(g,MECH).id
        g.apply(PlayCard(1,mid,position=0));self.assertEqual(g.state.magnetic_history[-1].target_id,host)
        self.assertEqual(self.grants(g,g.state.entities[host])[0].spell_damage_schools,(SpellSchool.FIRE,))
        self.play(g,FIRE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,498);self.portable(g)

    def test_Saruun_bounce_replay_removes_the_old_local_Fire_grant(self):
        g=self.game((SARUUN,DRAW,RETURN,FIRE),deck=(ELEMENTAL,A));self.play(g,SARUUN);self.play(g,DRAW);sid=self.play(g,ELEMENTAL)
        self.play(g,RETURN,sid);g.apply(PlayCard(1,sid));self.assertEqual(self.grants(g,g.state.entities[sid]),[])
        self.play(g,FIRE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).armor,499);self.portable(g)

    def test_Saruun_stored_wait_restore_and_drawn_later_recipient_does_not_rebind(self):
        g=self.game((SARUUN,),deck=(ELEMENTAL,ELEMENTAL),watch=True);self.play(g,SARUUN);self.fault(g);g=self.portable(g)
        self.choose(g,'draw');self.finish(g);cards=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==ELEMENTAL]
        self.assertEqual([len(self.grants(g,e))for e in cards],[1,0]);self.portable(g)

    def test_Halduron_real_hand_deck_Arcane_grants_and_actual_Missiles_budget(self):
        g=self.game((HALDURON,ARCANE,FIRE,MISSILES),deck=(ARCANE,FIRE));self.play(g,HALDURON)
        self.assertEqual(len(self.grants(g,self.entity(g,ARCANE))),1);self.assertEqual(self.grants(g,self.entity(g,FIRE)),[])
        self.assertEqual([len(self.grants(g,g.state.entities[i]))for i in g.state.players[1].deck],[1,0])
        self.play(g,MISSILES);self.assertEqual(g.state.split_damage_history[0].quote.budget,4);self.assertEqual(self.hero(g,2).armor,496);self.portable(g)

    def test_new_finite_declarations_reject_wrong_school_tribal_amount_and_spell_scope(self):
        with self.assertRaises(ValueError):PlayerAuraSpec(attack=1,scope='active_board_totems')
        with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.POISONOUS,'friendly_fel_spells')
        with self.assertRaises(ValueError):AbilityInstance(1,'spell_damage',source_id=1,spell_damage=2,spell_damage_schools=(SpellSchool.FIRE,))
        g=self.game((ELEMENTAL,),deck=(ELEMENTAL,));e=g.state.entities[g.state.players[1].deck[0]]
        with self.assertRaises(ValueError):GrantStoredSpellDamage(CardReference.capture(e),1,self.hero(g).id,schools=(SpellSchool.FROST,))
        with self.assertRaises(ValueError):GrantStoredSpellDamage(CardReference.capture(self.entity(g,ELEMENTAL)),1,self.hero(g).id,schools=(SpellSchool.FIRE,))


if __name__=='__main__':unittest.main()
