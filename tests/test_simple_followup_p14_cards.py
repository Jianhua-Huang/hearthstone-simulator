"""Original weapon hero-attack recipients and native successful after-casts."""
from dataclasses import asdict,replace
import json,re,unittest
from random import Random
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p14_cards import HAMMER,BROLL,FRAGMENT,ROOTS,COMPANIONS,load_batch,register_simple_followup_p14_cards
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Destroy,Draw,EquipWeapon,InvokeBehavior,ModifyWeapon,RequestChoice,ReturnToHand,Silence,Transform
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
TEST='p14.test.';YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry():
    r=build_registry();present=tuple(cid in r.cards for cid in ROOTS)
    if any(present)and not all(present):raise AssertionError('Partial P14 registration')
    if not all(present):register_simple_followup_p14_cards(r)
    for name,classes in(('paladin',(CardClass.PALADIN,)),('dual',(CardClass.PALADIN,CardClass.WARRIOR)),('neutral',(CardClass.NEUTRAL,)),('mage',(CardClass.MAGE,))):
        r.register_card(CardDefinition(TEST+name,name,CardType.MINION,attack=2,health=5,metadata=replace(META,classes=classes)))
    r.register_card(CardDefinition(TEST+'unknown','Unknown class',CardType.MINION,attack=2,health=5))
    r.register_card(CardDefinition(TEST+'dormant','Dormant Paladin',CardType.MINION,attack=2,health=5,dormant_turns=2,metadata=replace(META,classes=(CardClass.PALADIN,))))
    r.register_card(CardDefinition(TEST+'weapon','Other weapon',CardType.WEAPON,attack=2,durability=2,metadata=META))
    def broll_id(c):return next(i for p in(1,2)for i in c.state.players[p].board if c.state.entities[i].card_id==BROLL)
    def reenter(c):
        e=c.state.entities[c.target_id];return(SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
    r.register_behavior(TEST+'reenter',reenter)
    bodies={
        'noop':lambda c:(),
        'arcane':lambda c:(),
        'chip':lambda c:(ModifyWeapon(c.state.players[c.player_id].weapon_id,durability=-2,source_id=c.source_id),),
        'equip':lambda c:(EquipWeapon(c.player_id,TEST+'weapon'),),
        'to_paladin':lambda c:(Transform(c.target_id,TEST+'paladin'),),
        'to_neutral':lambda c:(Transform(c.target_id,TEST+'neutral'),),
        'kill_broll':lambda c:(Destroy(broll_id(c),c.source_id),),
        'silence_broll':lambda c:(Silence(broll_id(c)),),
        'give_broll':lambda c:(ChangeControl(broll_id(c),2),),
        'late_broll':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(BROLL),),SummonCause.capture(c)),),
        'driver':lambda c:(CastSpell(c.player_id,TEST+'noop',c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'bare':lambda c:(CombatDamage(next(i for i in c.state.players[1].board if c.state.entities[i].card_id==YETI),c.state.players[2].hero_id),),
        'choice':lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),),c.source_id),),
    }
    for name,body in bodies.items():
        key=TEST+name;r.register_behavior(key,body);kwargs={}
        if name in('to_paladin','to_neutral'):kwargs['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if name=='arcane':kwargs['spell_school']=SpellSchool.ARCANE
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=replace(META,classes=(CardClass.MAGE,)),**kwargs))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P14 deliberate pending failure')))
    def buff_wait(c):
        other=next(i for i in c.state.players[1].board if i!=c.event.target_id and c.state.entities[i].card_id==TEST+'paladin')
        return(RequestChoice(1,(
            ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),)),
            ChoiceOption('bounce','New residence',(ReturnToHand(other),InvokeBehavior(TEST+'reenter',c.source_id,1,other))),
            ChoiceOption('form','Different face',(Transform(other,TEST+'neutral'),)),
            ChoiceOption('control','Different controller',(ChangeControl(other,2),)),
        ),c.source_id),)
    def broll_wait(c):
        original=broll_id(c)
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),
            ChoiceOption('kill','Retire Broll',(Destroy(original,c.source_id),)),
        ),c.source_id),)
    def cancel(c):return(Destroy(c.event.target_id,c.source_id),)
    checks={
        'buff_wait':lambda c:c.state.entities[c.event.source_id].card_id==HAMMER,
        'summon_wait':lambda c:c.state.entities[c.event.target_id].card_id in COMPANIONS,
        'cast_wait':lambda c:c.event.player_id==c.player_id,
        'cancel':lambda c:c.event.source_id==c.state.players[c.player_id].hero_id,
    }
    for name,event,body in(('buff_wait','stats_changed',buff_wait),('summon_wait','minion_summoned',broll_wait),('cast_wait','spell_cast_finished',broll_wait),('cancel','attack_declared',cancel)):
        key=TEST+name;r.register_behavior(key,body);r.register_trigger_condition(key,checks[name])
        r.register_card(CardDefinition(key,name,CardType.MINION,health=8,metadata=META,limited_triggers=(LimitedTriggerSpec(event,key,condition_id=key),)))
    r.validate();return r

class SimpleFollowupP14Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),*,enemy_hand=(),deck=(YETI,)*8,active=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=1414),self.r)
    def entities(self,g,cid,p=1,zone='board'):return[g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None):
        p=g.state.active_player;source=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,source,target,len(g.state.players[p].board)if self.r.card(cid).kind==CardType.MINION else None));return source
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def attack(self,g,target=None):g.apply(Attack(1,g.state.players[1].hero_id,target or g.state.players[2].hero_id))
    def stats(self,g,eid):
        e=g.state.entities[eid];return(e.attack,e.max_health)
    def companions(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].board if g.state.entities[i].card_id in COMPANIONS]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry());self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','MinionReference','cast_history','behavior_id','source_allocation'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_six_complete_raw_records_twelve_official_faces_and_new_metadata(self):
        d=load_batch();rows=d['cards']+d['skipped']+d['existing_dependencies'];self.assertEqual(len(rows),6);self.assertEqual(len(d['official_observations']['observations']),12)
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in rows:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
                self.assertEqual((f['id'],f['manaCost'],f['cardTypeId'],f['cardSetId']),(raw['dbf_id'],raw['cost'],raw['tags']['CARDTYPE'],raw['card_set_id']))
            if raw['id']!=FRAGMENT:self.assertEqual(self.r.card(raw['id']).metadata,replace(metadata_from_record(raw),deck_identity=raw['id']))
        for o in d['official_observations']['observations']:
            if o['card_id']==BROLL:self.assertEqual(sorted(o['face']['childIds']),[100,226,959])
        self.assertNotIn(FRAGMENT,self.r.cards)

    def test_existing_companions_and_explicit_unregistered_baseline_are_complete(self):
        with patch('hs_sim.cards.simple_followup_p14_cards.register_simple_followup_p14_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS):register_simple_followup_p14_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS))
        for cid in COMPANIONS:self.assertEqual(asdict(before.card(cid)),asdict(after.card(cid)))

    def test_default_311_and_fingerprint_remain(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_hammer_exact_weapon_payment_and_only_current_paladin_board_minions(self):
        g=self.game((HAMMER,TEST+'paladin'),(TEST+'paladin',TEST+'dual',TEST+'neutral',TEST+'mage'),(TEST+'paladin',));source=self.play(g,HAMMER)
        ids=g.state.players[1].board;enemy=g.state.players[2].board[0];rng=g._rng.getstate();self.attack(g)
        self.assertEqual([self.stats(g,i)for i in ids],[(4,7),(4,7),(2,5),(2,5)]);self.assertEqual(self.stats(g,enemy),(2,5))
        self.assertEqual(self.first(g,TEST+'paladin',zone='hand').attack,2);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].durability,g.state.players[1].mana),(3,2,33))
        self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_hammer_current_transformed_face_controls_class_not_former_metadata(self):
        g=self.game((HAMMER,TEST+'to_paladin',TEST+'to_neutral'),(TEST+'neutral',TEST+'paladin'));a,b=g.state.players[1].board
        self.play(g,TEST+'to_paladin',a);self.play(g,TEST+'to_neutral',b);self.play(g,HAMMER);self.attack(g)
        self.assertEqual([self.stats(g,i)for i in(a,b)],[(4,7),(2,5)]);self.portable(g)

    def test_hammer_last_wear_accepted_reward_survives_weapon_retirement(self):
        g=self.game((HAMMER,TEST+'chip'),(TEST+'paladin',));source=self.play(g,HAMMER);self.play(g,TEST+'chip');self.attack(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(self.stats(g,g.state.players[1].board[0]),(4,7));self.portable(g)

    def test_hammer_minion_attack_and_bare_compatibility_combat_do_not_claim_hero_credit(self):
        g=self.game((HAMMER,TEST+'bare'),(TEST+'paladin',YETI));self.play(g,HAMMER);g.apply(Attack(1,self.first(g,YETI).id,g.state.players[2].hero_id));self.play(g,TEST+'bare')
        self.assertEqual(self.stats(g,self.first(g,TEST+'paladin').id),(2,5));self.assertEqual(len(g.state.character_attack_history),1)

    def test_hammer_opponent_hero_attack_is_not_own_hero_credit(self):
        g=self.game((HAMMER,),(TEST+'paladin',),enemy_hand=(TEST+'equip',));self.play(g,HAMMER);g.apply(EndTurn(1));self.play(g,TEST+'equip')
        g.apply(Attack(2,g.state.players[2].hero_id,g.state.players[1].hero_id));self.assertEqual(self.stats(g,self.first(g,TEST+'paladin').id),(2,5));self.portable(g)

    def test_hammer_cancelled_declared_attack_has_no_reward(self):
        g=self.game((HAMMER,),(TEST+'cancel',TEST+'paladin'),(YETI,));source=self.play(g,HAMMER);self.attack(g,g.state.players[2].board[0])
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled');self.assertEqual(self.stats(g,self.first(g,TEST+'paladin').id),(2,5));self.assertEqual(g.state.entities[source].durability,3)

    def test_hammer_dormant_excluded_and_unknown_current_class_rolls_back_entire_attack(self):
        g=self.game((HAMMER,),(TEST+'paladin',TEST+'dormant'));self.play(g,HAMMER);self.attack(g)
        self.assertEqual(self.stats(g,self.first(g,TEST+'dormant').id),(2,5))
        g=self.game((HAMMER,),(TEST+'paladin',TEST+'unknown'));self.play(g,HAMMER);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'class is unknown'):self.attack(g)
        self.assertEqual(g.snapshot(),saved)

    def test_hammer_captured_remaining_buffs_restore_and_never_rebind_changed_original(self):
        for key in('bounce','form','control'):
            with self.subTest(key=key):
                g=self.game((HAMMER,),(TEST+'buff_wait',TEST+'paladin',TEST+'paladin'));old=g.state.players[1].board[-1];self.play(g,HAMMER);self.attack(g)
                other=self.portable(g);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'fail')
                self.assertEqual(g.snapshot(),saved);self.choose(g,key);self.choose(other,key);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.stats(g,old),(2,5));self.portable(g)

    def test_broll_paid_minion_waits_for_actual_successful_payload_completion(self):
        g=self.game((BROLL,TEST+'choice'));source=self.play(g,BROLL);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health,g.state.players[1].mana),(3,5,35))
        self.play(g,TEST+'choice');self.assertFalse(self.companions(g));self.assertFalse(g.state.cast_history[-1].completed);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.companions(g)),1);self.portable(g)

    def test_broll_one_uniform_complete_family_sample_with_native_cause(self):
        g=self.game((TEST+'noop',),(BROLL,));rng=Random();rng.setstate(g._rng.getstate());expected=rng.choice(COMPANIONS);self.play(g,TEST+'noop')
        self.assertEqual([e.card_id for e in self.companions(g)],[expected]);self.assertEqual(g._rng.getstate(),rng.getstate())
        cause=g.state.card_summon_history[-1].request.cause;self.assertEqual((cause.source.card_id,cause.origin,cause.cast_id),(BROLL,'card_effect',None));self.portable(g)

    def test_broll_does_not_trigger_for_opponent_spell_or_countered_attempt(self):
        g=self.game(board=(BROLL,),enemy_hand=(TEST+'noop',),active=2);self.play(g,TEST+'noop');self.assertFalse(self.companions(g))
        g=self.game((TEST+'noop',),(BROLL,),enemy_hand=('CORE_EX1_287',),active=2);self.play(g,'CORE_EX1_287');g.apply(EndTurn(2));self.play(g,TEST+'noop')
        self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertFalse(self.companions(g));self.portable(g)

    def test_broll_source_killed_silenced_or_given_away_during_payload_is_not_own_finish_listener(self):
        for cid in('kill_broll','silence_broll','give_broll'):
            with self.subTest(cid=cid):
                g=self.game((TEST+cid,),(BROLL,));self.play(g,TEST+cid);self.assertFalse(self.companions(g));self.assertFalse(self.companions(g,2));self.portable(g)

    def test_broll_newly_summoned_during_payload_is_present_at_after_cast_window(self):
        g=self.game((TEST+'late_broll',));self.play(g,TEST+'late_broll');self.assertEqual(len(self.entities(g,BROLL)),1);self.assertEqual(len(self.companions(g)),1);self.portable(g)

    def test_broll_each_actual_hand_repetition_has_its_own_completion(self):
        g=self.game((TEST+'arcane',),(BROLL,'RLK_541'));self.play(g,TEST+'arcane')
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','repeat']);self.assertEqual(len(self.companions(g)),2);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_broll_effect_cast_and_outer_hand_cast_each_finish_without_extra_payment(self):
        g=self.game((TEST+'driver',),(BROLL,));self.play(g,TEST+'driver');self.assertEqual([c.origin for c in g.state.cast_history],['hand','effect'])
        self.assertEqual(len(self.companions(g)),2);self.assertEqual(len(g.state.play_history),1);self.assertEqual(g.state.players[1].mana,40);self.portable(g)

    def test_broll_draw_cast_and_parent_completion_use_native_replacement_chain(self):
        g=self.game((TEST+'draw',),(BROLL,),deck=('JAIL_443t',YETI,YETI));self.play(g,TEST+'draw')
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','draw']);self.assertEqual(len(self.companions(g)),2);self.assertEqual(len(g.state.players[1].hand),1);self.portable(g)

    def test_broll_full_board_skips_without_sampling_or_replacing_materials(self):
        g=self.game((TEST+'noop',),(BROLL,)+(YETI,)*6);rng=g._rng.getstate();self.play(g,TEST+'noop')
        self.assertFalse(self.companions(g));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(g.state.card_summon_history),1)

    def test_broll_quantity_extras_keep_same_one_random_selected_companion(self):
        g=self.game((TEST+'noop',),(BROLL,'CORE_DAL_575'));rng=Random();rng.setstate(g._rng.getstate());expected=rng.choice(COMPANIONS);self.play(g,TEST+'noop')
        self.assertEqual([e.card_id for e in self.companions(g)],[expected,expected]);self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)

    def test_broll_selected_summon_wait_restore_failure_and_later_source_retirement_keep_selection(self):
        g=self.game((TEST+'noop',),(BROLL,TEST+'summon_wait'));self.play(g,TEST+'noop');selected=[e.card_id for e in self.companions(g)];self.assertEqual(len(selected),1)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'kill');self.choose(other,'kill');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([e.card_id for e in self.companions(g)],selected);self.portable(g)

    def test_broll_already_captured_finish_trigger_survives_earlier_listener_killing_source(self):
        g=self.game((TEST+'noop',),(TEST+'cast_wait',BROLL));self.play(g,TEST+'noop');self.assertFalse(self.companions(g));other=self.portable(g)
        self.choose(g,'kill');self.choose(other,'kill');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.companions(g)),1);self.assertFalse(self.entities(g,BROLL));self.portable(g)

if __name__=='__main__':unittest.main()
