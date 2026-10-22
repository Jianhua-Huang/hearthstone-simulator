"""Native player budgets, prices and programs survive actual new carriers."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_player_modifier_fragments import SOURCES,RECRUIT,load_batch,register_assemble_player_modifier_fragments
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,Draw,GainArmor,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,DamageKind,Keyword,SpellSchool
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.temporary_cards import CreateTemporaryCard
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture,META,COIN,KILL,MUTE,BOUNCE

KALEC,THERAZANE,DEMON_NEXT,NEOPHYTE,TYRANDE,RIGHTMOST,CRYSTALS,LO,CAVE,OFFICER=SOURCES
LOOT,HEAL,DOOM='CORE_EX1_096','EDR_971','CORE_NEW1_021'
P='fixture.assemble_player_modifier.'
A,DEMON,AUTO,DRAW,GET_FIRE,GET_A,GET_TEMP,RECRUIT_SPELL,WATCH,FAULT=(P+x for x in
    ('ordinary','demon','automatic','draw','get_fire','get_ordinary','get_temp','recruit','watch','fault'))
SPELLS={s:P+s.value for s in SpellSchool}
FIRE,FROST,ARCANE=SPELLS[SpellSchool.FIRE],SPELLS[SpellSchool.FROST],SPELLS[SpellSchool.ARCANE]
PLAIN=P+'schoolless'
CTX=GenerationContext('k410-reviewed-player-modifiers','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k410.'+mode
    for cid,cost,tribes in((A,4,()),(DEMON,5,('demon',))):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=5,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    def hit(c):return(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),)
    r.register_behavior(P+'hit',hit)
    for school,cid in((*SPELLS.items(),(None,PLAIN))):
        d=CardDefinition(cid,cid,CardType.SPELL,cost=3,on_play=P+'hit',spell_school=school,metadata=META)
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,FIRE,c.source_id,choices='player'),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,cost=1,attack=1,health=4,battlecry=AUTO,metadata=META))
    bodies={DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),
        GET_FIRE:lambda c:(AddToHand(c.player_id,FIRE,c.source_id),),
        GET_A:lambda c:(AddToHand(c.player_id,A,c.source_id),),
        GET_TEMP:lambda c:tuple(CreateTemporaryCard(c.player_id,cid,c.state.turn,source_id=c.source_id)for cid in(FIRE,A)),
        RECRUIT_SPELL:lambda c:(Summon(c.player_id,RECRUIT),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META))
    def fail(c):raise ResolutionError('assembled cost installation deliberate failure')
    r.register_behavior(FAULT,fail)
    def watch(c):
        if c.event.player_id!=c.player_id:return()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('fault','Fail',(
            GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=META,
        triggers=(TriggerSpec('cost_modifier_added',WATCH),)))
    if mode=='missing':r._assemble_templates.pop(NEOPHYTE)
    if mode!='no_assembly':r.register_pool(PoolDefinition(POOL_ID,'three-real-player-modifier-sources-v1',CTX.target_id,
        CTX.mode,tuple(PoolMember(x)for x in(NEOPHYTE,'CORE_GVG_114','CORE_EX1_110')),complete=True))
    return r


class AssemblePlayerModifierTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=None,mode='normal',economy=(30,30,30)):
        self.mode=mode;mana,maximum,cap=economy
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=(COIN,)*12 if deck is None else deck,mana=mana,max_mana=maximum,mana_cap=cap),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(COIN,)*12,mana=mana,max_mana=maximum,mana_cap=cap)),
            seed=410,generation_context=CTX),fixture(mode))
    def entity(self,g,cid,zone='hand',pid=1):
        return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=self.entity(g,cid,pid=pid).id;g.apply(PlayCard(pid,eid,target_id=target));return eid
    def price(self,g,cid,pid=1):
        state=g.state;eid=next(i for i in state.players[pid].hand if state.entities[i].card_id==cid)
        return quote_cost(state,g.registry,state.entities[eid]).amount
    def price_id(self,g,eid):
        state=g.state;return quote_cost(state,g.registry,state.entities[eid]).amount
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def health(self,g,pid=2):return g.state.entities[g.state.players[pid].hero_id].health
    def bonus(self,e):return sum(a.spell_damage for a in e.abilities if a.kind=='spell_damage'and not a.consumed)
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def test_eleven_complete_records_twenty_two_primary_faces_and_two_original_programs(self):
        data=load_batch();r=build_registry();rows={x['record']['id']:x for x in data['existing_dependencies']}
        self.assertEqual(tuple(rows),SOURCES+(RECRUIT,));self.assertEqual(len(data['official_observations']),22)
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'])
            p=Path(obs['response_file']);self.assertEqual(sha(p),obs['response_sha256'])
            self.assertEqual([f for f in json.loads(p.read_text('utf-8-sig'))['cards']if f['id']==row['record']['dbf_id']],[obs['face']])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for key,pin in data['player_program_pins'].items():self.assertEqual(canonical_digest(asdict(r.player_effect(key))),canonical_digest(pin))
        self.assertEqual(len(data['recruit_recipient_ids']),9)

    def test_all_ten_whole_faces_reconstruct_with_original_callbacks_and_readonly_lookup(self):
        r=build_registry();fp=r.fingerprint();count=len(r.cards)
        for cid in SOURCES:
            d=r.card(cid);t=r.assemble_templates[cid];face=r.card(AssembleRecipe(cid,cid,'top').card_id)
            self.assertEqual(asdict(face),asdict(d)|{'id':face.id})
            self.assertEqual(t.suffix.behavior_id,d.battlecry or d.deathrattle)
            self.assertIsNone(t.prefix.before_behavior_id)
        self.assertEqual((r.fingerprint(),len(r.cards)),(fp,count))

    def test_stored_spell_bonus_stays_on_original_hand_deck_spells_after_source_death(self):
        cid=AssembleRecipe(KALEC,KALEC,'top').card_id
        g=self.game(hand=(cid,FIRE,A,DRAW,GET_FIRE,KILL),deck=(FROST,A,COIN));mana=g.state.players[1].mana
        eid=self.play(g,cid);self.assertEqual(g.state.players[1].mana,mana-g.registry.card(cid).cost)
        self.assertEqual(self.bonus(self.entity(g,FIRE)),1);self.assertEqual(self.bonus(self.entity(g,FROST,'deck')),1)
        self.assertEqual(self.bonus(self.entity(g,A)),0);self.play(g,KILL,eid);self.play(g,FIRE);self.assertEqual(self.health(g),28)
        self.play(g,GET_FIRE);self.assertEqual(self.bonus(self.entity(g,FIRE)),0);self.play(g,FIRE);self.assertEqual(self.health(g),27)
        self.play(g,DRAW);self.assertEqual(self.bonus(self.entity(g,FROST)),1);self.play(g,FROST);self.assertEqual(self.health(g),25)

    def test_dead_therazane_half_has_seven_independent_budgets_and_real_automatic_cast(self):
        cid=AssembleRecipe(LOOT,THERAZANE,'bottom').card_id
        g=self.game(hand=(KILL,AUTO,FIRE,PLAIN,FROST),board=(cid,));eid=g.state.players[1].board[0];self.play(g,KILL,eid)
        self.assertEqual(len(g.state.players[1].spell_modifiers),7);self.assertFalse(g.state.draw_history)
        self.play(g,AUTO);self.assertEqual(self.health(g),28)
        self.play(g,FIRE);self.assertEqual(self.health(g),27)
        self.play(g,PLAIN);self.assertEqual(self.health(g),26)
        self.play(g,FROST);self.assertEqual(self.health(g),24)

    def test_dead_tyrande_half_preserves_three_manual_uses_without_spending_on_automatic_cast(self):
        cid=AssembleRecipe(LOOT,TYRANDE,'bottom').card_id
        g=self.game(hand=(KILL,AUTO,FIRE,FROST,ARCANE,FIRE),board=(cid,));self.play(g,KILL,g.state.players[1].board[0])
        self.play(g,AUTO);self.assertEqual(self.health(g),29)
        for card,health in((FIRE,27),(FROST,25),(ARCANE,23),(FIRE,22)):
            self.play(g,card);self.assertEqual(self.health(g),health)
        self.assertEqual(g.state.players[1].mana,17)

    def test_next_demon_price_survives_other_card_silence_and_source_death_then_consumes_once(self):
        cid=AssembleRecipe(DEMON_NEXT,DEMON_NEXT,'top').card_id;g=self.game(hand=(cid,DEMON,DEMON,A,MUTE,KILL))
        eid=self.play(g,cid);self.assertEqual(self.price(g,DEMON),3);self.assertEqual(self.price(g,A),4)
        self.play(g,A);self.assertEqual(self.price(g,DEMON),3);self.play(g,MUTE,eid);self.play(g,KILL,eid)
        before=g.state.players[1].mana;self.play(g,DEMON);self.assertEqual(g.state.players[1].mana,before-3)
        self.assertEqual(self.price(g,DEMON),5)

    def test_next_temporary_discount_uses_actual_lifetime_and_one_payment_after_source_death(self):
        cid=AssembleRecipe(CAVE,CAVE,'top').card_id;g=self.game(hand=(cid,GET_TEMP,FIRE,KILL));eid=self.play(g,cid)
        before=set(g.state.players[1].hand);self.play(g,GET_TEMP)
        added=[g.state.entities[i]for i in g.state.players[1].hand if i not in before]
        fire=next(e.id for e in added if e.card_id==FIRE);ordinary=next(e.id for e in added if e.card_id==A)
        self.assertEqual(self.price_id(g,fire),1);self.assertEqual(self.price_id(g,ordinary),2)
        self.play(g,FIRE);self.assertEqual(self.price_id(g,fire),1);self.play(g,KILL,eid)
        before=g.state.players[1].mana;self.play(g,FIRE);self.assertEqual(g.state.players[1].mana,before-1)
        self.assertEqual(self.price_id(g,ordinary),4)

    def test_opponent_tax_is_pending_until_next_real_enemy_start_and_expires_after_that_turn(self):
        cid=AssembleRecipe(NEOPHYTE,NEOPHYTE,'top').card_id;g=self.game(hand=(cid,KILL),enemy_hand=(FIRE,A))
        eid=self.play(g,cid);self.play(g,KILL,eid);self.assertEqual(self.price(g,FIRE,2),3)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,FIRE,2),4);self.assertEqual(self.price(g,A,2),4)
        g.apply(EndTurn(2));self.assertEqual(self.price(g,FIRE,2),3)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,FIRE,2),3)

    def test_rightmost_discount_reuses_fresh_hand_after_play_in_battlecry_and_deathrattle(self):
        for primary in(RIGHTMOST,'CORE_KAR_061'):
            with self.subTest(primary=primary):
                cid=AssembleRecipe(primary,RIGHTMOST,'bottom').card_id;g=self.game(hand=(A,KILL,FIRE,cid))
                eid=self.play(g,cid)
                self.assertEqual(self.price(g,FIRE),3 if primary==RIGHTMOST else 1)
                self.play(g,KILL,eid);self.assertEqual(self.price(g,FIRE),1)
                self.assertEqual(self.price(g,A),4);self.assertFalse(g.state.draw_history)

    def test_empty_crystals_grow_both_players_without_refilling_and_respect_capacity(self):
        cid=AssembleRecipe(CRYSTALS,CRYSTALS,'top').card_id
        for maximum in(5,10):
            with self.subTest(maximum=maximum):
                g=self.game(hand=(KILL,),board=(cid,),economy=(3,maximum,10));self.play(g,KILL,g.state.players[1].board[0])
                for pid in(1,2):self.assertEqual((g.state.players[pid].mana,g.state.players[pid].max_mana),(3,min(maximum+1,10)))

    def test_whole_game_five_mana_minions_cover_future_cards_and_outlive_silenced_dead_source(self):
        cid=AssembleRecipe(LO,LO,'top').card_id;g=self.game(hand=(cid,A,DEMON,FIRE,KILL,MUTE,GET_A))
        eid=self.play(g,cid);self.assertEqual(self.price(g,A),5);self.assertEqual(self.price(g,DEMON),5)
        self.assertEqual(self.price(g,FIRE),3);self.play(g,MUTE,eid);self.play(g,KILL,eid)
        before=g.state.players[1].mana;self.play(g,A);self.assertEqual(g.state.players[1].mana,before-5)
        self.assertEqual(self.price(g,DEMON),5);self.play(g,GET_A);self.assertEqual(self.price(g,A),5)

    def test_dead_recruit_program_targets_own_stored_board_and_future_recruits_not_enemy(self):
        cid=AssembleRecipe(LOOT,OFFICER,'bottom').card_id
        g=self.game(hand=(KILL,RECRUIT,RECRUIT_SPELL),board=(cid,RECRUIT),enemy=(RECRUIT,),
            enemy_hand=(RECRUIT,),deck=(RECRUIT,COIN));eid=g.state.players[1].board[0]
        self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords);self.play(g,KILL,eid)
        for zone in('hand','deck','board'):self.assertEqual(self.entity(g,RECRUIT,zone).attack,2)
        self.assertEqual(self.entity(g,RECRUIT,'board',2).attack,1);self.assertEqual(self.entity(g,RECRUIT,pid=2).attack,1)
        self.play(g,RECRUIT_SPELL)
        recruits=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==RECRUIT]
        self.assertEqual([e.attack for e in recruits],[2,2]);self.assertFalse(g.state.draw_history)
        program=g.state.players[1].player_effects[-1];self.assertEqual(program.source_id,eid);self.assertEqual(program.source_card_id,cid)

    def test_real_mismatch_entry_borrows_tax_into_deathrattle_without_old_cairne_summon(self):
        g=self.game(hand=(MISMATCH,KILL),enemy_hand=(FIRE,));self.play(g,MISMATCH)
        cid=AssembleRecipe(NEOPHYTE,'CORE_EX1_110','top').card_id;q=g.state.pending_choice
        self.choose(g,next(o.id for o in q.options if o.card_id==cid));eid=self.play(g,cid)
        self.assertFalse(g.state.players[2].player_effects);self.play(g,KILL,eid)
        self.assertEqual(len(g.state.players[2].player_effects),1);self.assertEqual(len(g.state.players[1].board),1)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,FIRE,2),4)

    def test_cost_install_waiting_preserves_one_original_budget_payment_replay_and_player_boundary(self):
        cid=AssembleRecipe(DEMON_NEXT,DEMON_NEXT,'top').card_id
        g=self.game(hand=(cid,DEMON),board=(WATCH,));before=g.state.players[1].mana;self.play(g,cid)
        self.assertEqual(self.price(g,DEMON),3);saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'installation deliberate failure'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok')
        self.assertEqual(g.state.players[1].mana,before-g.registry.card(cid).cost)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1)
        self.play(g,DEMON);self.assertIsNone(g.state.pending_choice)
        public=json.dumps(g.observe(2),ensure_ascii=False)
        for hidden in('quote_input','resolution_frame','source_sha256','definition_sha256'):self.assertNotIn(hidden,public)

    def test_unknown_eligible_source_changed_complete_source_recruit_or_program_is_atomic(self):
        for mode in('missing','no_assembly'):
            g=self.game(hand=(MISMATCH,),mode=mode);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,MISMATCH)
            self.assertEqual(g.snapshot(),saved)
        for changed in(KALEC,RECRUIT,'program'):
            r=build_registry()
            for cid in SOURCES:r._assemble_templates.pop(cid)
            if changed=='program':
                key='cards.player_period.neophyte';r._player_effects[key]=replace(r.player_effect(key),card_id=KALEC)
            else:r._cards[changed]=replace(r.card(changed),attack=r.card(changed).attack+1)
            with self.assertRaises(TargetValidationError):register_assemble_player_modifier_fragments(r)
            self.assertFalse(set(SOURCES)&set(r.assemble_templates))


if __name__=='__main__':unittest.main()
