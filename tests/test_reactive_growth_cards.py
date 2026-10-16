"""Real trigger cards: event identity, before/after, original references and recovery."""
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.reactive_growth_cards import load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,TriggerSpec,UseHeroPower,Zone,CastWhenDrawnSpec)
from hs_sim.engine.dormancy import AwakenCapturedMinion,AwakenMinion,MakeDormant
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,DamageBatch,Destroy,Draw,
    InvokeBehavior,RequestChoice,Silence)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import DamageKind,TribeChangeSpec,SpellSchool
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.spell_casts import CastSpell,CastStoredSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TIDE='CORE_EX1_509';ANTO='CORE_EX1_559';FROTH='CORE_EX1_604';MICRO='CORE_GVG_103';PYRO='CORE_NEW1_020'
ACOL='CORE_RLK_121';VAPOR='CORE_WC_042';BARK='EDR_470';TORT='EDR_471';PLANT='EDR_484';BANE='CORE_DRG_256';SLEEP='EDR_469'
ROOTS=(TIDE,ANTO,FROTH,MICRO,PYRO,ACOL,VAPOR,BARK,TORT,PLANT,BANE,SLEEP);YETI='CORE_CS2_182';FIRE='CS2_029'


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_card(CardDefinition('k27.undead','Undead fixture',CardType.MINION,attack=2,health=2,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('undead',))))
    r.register_card(CardDefinition('k27.unknown','Unknown tribe fixture',CardType.MINION,attack=1,health=2,
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=None)))
    def ids(c):return tuple(i for p in (1,2)for i in c.state.players[p].board if c.state.entities[i].active and c.state.entities[i].kind==CardType.MINION)
    def wake_choice(c):
        entity=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SLEEP)
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Wake',(
            AwakenCapturedMinion(MinionReference.capture(entity),entity.dormancy.id,c.source_id),)),
            ChoiceOption('bad','Fail',(InvokeBehavior('k27.fail',c.source_id,c.player_id),))),c.source_id),)
    scripts={
        'noop':lambda c:(),
        'ping':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'all1':lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)for i in ids(c))),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'grow':lambda c:(Buff(c.target_id,attack=3,source_id=c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'summon_elemental':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial('CS2_033'),),SummonCause.capture(c)),),
        'undead':lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('undead',)),c.source_id),),
        'elemental_hand':lambda c:(ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('elemental',)),c.source_id),),
        'wake_choice':wake_choice,
        'repeat_probe':lambda c:()if c.cast.iteration==1 else(RequestChoice(c.player_id,(ChoiceOption('ok','Finish repeat'),),c.source_id),),
    }
    for name,body in scripts.items():
        key='k27.op.'+name;r.register_behavior(key,body)
        extra={'targeting':TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')}if name=='elemental_hand'else{
            'requires_target':name in ('ping','kill','grow','silence','undead')}
        r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=meta,**extra))
    r.register_card(CardDefinition('k27.repeat_probe','Repeat window fixture',CardType.SPELL,
        on_play='k27.op.repeat_probe',spell_school=SpellSchool.ARCANE,metadata=meta))
    r.register_card(CardDefinition('k27.draw_cast','Draw-cast fixture',CardType.SPELL,
        on_play='k27.op.noop',keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=False),metadata=meta))
    r.register_card(CardDefinition('k27.no_target','Failed automatic fixture',CardType.SPELL,
        on_play='k27.op.noop',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=meta))
    drivers={
        'generated':lambda c:(CastSpell(c.player_id,'k27.op.noop',c.source_id),),
        'stored':lambda c:(CastStoredSpell(CardReference.capture(next(e for e in c.state.entities.values()
            if e.card_id=='k27.op.noop'and e.zone==Zone.HAND)),c.player_id,c.source_id),),
        'history':lambda c:(RecastSpell(c.player_id,c.state.cast_history[0].id,c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
        'failed':lambda c:(CastSpell(c.player_id,'k27.no_target',c.source_id),),
    }
    for name,body in drivers.items():
        key='k27.driver.'+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,name,CardType.MINION,health=1,battlecry=key,metadata=meta))
    r.register_behavior('k27.fail',lambda c:(AddToHand(c.player_id,'missing.k27'),))
    if mode:
        def watch(c):
            if c.event.player_id!=c.player_id:return ()
            if mode=='redormant':
                entity=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SLEEP)
                return (AwakenMinion(entity.id,c.source_id),MakeDormant(entity.id,None,c.source_id))
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        r.register_behavior('k27.watch',watch)
        r.register_card(CardDefinition('k27.watch','Earlier power observer',CardType.MINION,health=8,metadata=meta,
            triggers=(TriggerSpec('hero_power_used','k27.watch'),)))
    return r


class ReactiveGrowthCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),active=1,mode=None,deck=(YETI,)*14):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,
            deck=(YETI,)*14,hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=427),registry(mode)if mode else self.r)
    def eid(self,g,cid,p=1,zone='board'):return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def entity(self,g,cid,p=1):return g.state.entities[self.eid(g,cid,p)]
    def play(self,g,cid,target=None):
        p=g.state.active_player;i=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,i,target));return i
    def op(self,g,name,target=None):return self.play(g,'k27.op.'+name,target)
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def power(self,g,target=None):
        p=g.state.active_player;g.apply(UseHeroPower(p,g.state.players[p].hero_power_id,target or self.hero(g,3-p).id))
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=g.snapshot();other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return other

    def test_complete_twelve_raw_roots_and_named_fireball_dependency(self):
        batch=load_batch();self.assertEqual(tuple(x['record']['id']for x in batch['cards']),ROOTS)
        for row in batch['cards']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(self.r.card(row['record']['id']).metadata.deck_identity,row['recipe']['deck_identity'])
        dependency=batch['reused_dependencies'][0];self.assertEqual((dependency['dbf'],dependency['record']['id']),(315,FIRE))
        self.assertEqual(self.r.card(ANTO).triggers[0].event,'spell_cast_started')
        self.assertEqual(self.r.card(PYRO).triggers[0].event,'card_played')

    def test_each_real_root_pays_once_and_installs_its_full_printed_body(self):
        for cid in ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,));i=self.play(g,cid);card=g.registry.card(cid);e=g.state.entities[i]
                self.assertEqual((e.attack,e.health),(card.attack,card.health));self.assertEqual(g.state.players[1].mana,40-card.cost)
                self.assertEqual(e.dormancy is not None,cid==SLEEP);self.assertEqual(sum(v.kind=='card_played'for v in g.events),1)

    def test_tidecaller_excludes_itself_and_counts_both_real_tidehunter_summons(self):
        g=self.game((TIDE,'CORE_EX1_506'));i=self.play(g,TIDE);self.assertEqual(g.state.entities[i].attack,1)
        self.play(g,'CORE_EX1_506');self.assertEqual(g.state.entities[i].attack,3);self.portable(g)

    def test_tidecaller_does_not_count_opponent_summons(self):
        g=self.game(board=(TIDE,),enemy_hand=('CORE_EX1_506',),active=2);self.play(g,'CORE_EX1_506')
        self.assertEqual(self.entity(g,TIDE).attack,1)

    def test_antonidas_gives_fireball_before_the_spell_kills_him(self):
        g=self.game(('k27.op.all1','CORE_CS2_029'),board=(ANTO,));i=self.eid(g,ANTO)
        self.op(g,'all1');self.play(g,'CORE_CS2_029',i)
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertEqual([g.state.entities[j].card_id for j in g.state.players[1].hand],[FIRE,FIRE]);self.portable(g)

    def test_countered_cast_starts_antonidas_but_does_not_complete_for_pyromancer(self):
        g=self.game(('k27.op.noop',),board=(ANTO,PYRO),enemy=(YETI,),enemy_hand=('EX1_287',),active=2)
        self.play(g,'EX1_287');self.end(g);self.op(g,'noop')
        self.assertEqual(g.state.cast_history[-1].failure,'countered')
        self.assertIn(FIRE,[g.state.entities[j].card_id for j in g.state.players[1].hand])
        self.assertEqual(self.entity(g,PYRO).health,2);self.assertEqual(self.entity(g,YETI,2).health,5);self.portable(g)

    def test_antonidas_and_pyromancer_count_personal_play_once_despite_two_casts(self):
        g=self.game(('CORE_CS2_023',),board=(ANTO,PYRO,'RLK_541'));self.play(g,'CORE_CS2_023')
        self.assertEqual(sum(g.state.entities[j].card_id==FIRE for j in g.state.players[1].hand),1)
        self.assertEqual(self.entity(g,PYRO).health,1)
        self.assertEqual(sum(v.kind=='spell_cast_started'for v in g.events),2);self.portable(g)

    def test_pyromancer_waits_for_whole_paid_play_and_pending_repeat_restores(self):
        g=self.game(('k27.repeat_probe',),board=(ANTO,PYRO,'RLK_541'));self.play(g,'k27.repeat_probe')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.entity(g,PYRO).health,2)
        self.assertEqual(sum(g.state.entities[j].card_id==FIRE for j in g.state.players[1].hand),1)
        restored=self.portable(g)
        for branch in(g,restored):self.choose(branch);self.assertEqual(self.entity(branch,PYRO).health,1)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_automatic_generated_stored_history_draw_and_failed_casts_do_not_count_as_you(self):
        for route in('generated','stored','history','draw','failed'):
            with self.subTest(route=route):
                g=self.game(('k27.op.noop','k27.driver.'+route),board=(ANTO,PYRO),deck=('k27.draw_cast',YETI))
                if route=='history':self.op(g,'noop')
                before=sum(g.state.entities[j].card_id==FIRE for j in g.state.players[1].hand)
                health=self.entity(g,PYRO).health
                self.play(g,'k27.driver.'+route)
                self.assertEqual(sum(g.state.entities[j].card_id==FIRE for j in g.state.players[1].hand),before)
                self.assertEqual(self.entity(g,PYRO).health,health)
                self.assertEqual(g.state.cast_history[-1].origin,dict(generated='effect',stored='effect',history='history',draw='draw',failed='effect')[route])
                if route=='failed':self.assertEqual(g.state.cast_history[-1].failure,'no_target')
                self.portable(g)

    def test_pyromancer_does_not_run_after_the_spell_kills_its_source(self):
        g=self.game(('CORE_CS2_029',),board=(PYRO,),enemy=(YETI,));i=self.eid(g,PYRO)
        self.play(g,'CORE_CS2_029',i);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertEqual(self.entity(g,YETI,2).health,5)

    def test_pyromancer_damage_is_minion_ability_not_spell_damage(self):
        g=self.game(('k27.op.noop',),board=(PYRO,'TIME_856'),enemy=(YETI,));self.op(g,'noop')
        self.assertEqual(self.entity(g,YETI,2).health,4);self.assertEqual(self.entity(g,PYRO).health,1)

    def test_frothing_counts_positive_minion_damage_not_hero_or_prevented_packets(self):
        g=self.game(('k27.op.ping','k27.op.all1'),board=(FROTH,'CORE_EX1_008'),enemy=(YETI,))
        self.op(g,'ping',self.hero(g).id);self.assertEqual(self.entity(g,FROTH).attack,2)
        self.op(g,'all1');self.assertEqual(self.entity(g,FROTH).attack,4);self.portable(g)

    def test_acolyte_uses_friendly_death_and_current_frozen_undead_tribe(self):
        g=self.game(('k27.op.kill','k27.op.undead','k27.op.kill'),board=(ACOL,YETI),enemy=('k27.undead',))
        self.op(g,'kill',self.eid(g,'k27.undead',2));self.assertFalse(g.state.draw_history)
        target=self.eid(g,YETI);self.op(g,'undead',target);self.op(g,'kill',target)
        self.assertEqual(len(g.state.draw_history),1);self.portable(g)

    def test_carnivorous_gains_original_final_death_attack_from_either_player(self):
        g=self.game(('k27.op.grow','k27.op.kill'),board=(PLANT,),enemy=(YETI,));target=self.eid(g,YETI,2)
        self.op(g,'grow',target);self.op(g,'kill',target);self.assertEqual(self.entity(g,PLANT).attack,9)
        self.assertEqual(g.state.death_history[-1].attack,7);self.portable(g)

    def test_micro_machine_grows_at_each_actual_players_start(self):
        g=self.game(board=(MICRO,));self.assertEqual(self.entity(g,MICRO).attack,1)
        self.end(g);self.assertEqual(self.entity(g,MICRO).attack,2);self.end(g)
        self.assertEqual(self.entity(g,MICRO).attack,3);self.portable(g)

    def test_vapor_counts_played_elemental_but_not_itself_or_an_effect_summon(self):
        g=self.game((VAPOR,'CS2_033','k27.op.summon_elemental'));self.play(g,VAPOR)
        self.assertEqual(self.entity(g,VAPOR).attack,1);self.play(g,'CS2_033');self.assertEqual(self.entity(g,VAPOR).attack,2)
        self.op(g,'summon_elemental');self.assertEqual(self.entity(g,VAPOR).attack,2);self.portable(g)

    def test_vapor_uses_original_hand_tribe_operands_not_a_later_printed_guess(self):
        g=self.game(('k27.op.elemental_hand',YETI),board=(VAPOR,));target=self.eid(g,YETI,zone='hand')
        self.op(g,'elemental_hand',target);self.play(g,YETI);self.assertEqual(self.entity(g,VAPOR).attack,2);self.portable(g)

    def test_unknown_played_tribe_fails_explicitly_and_rolls_back(self):
        g=self.game(('k27.unknown',),board=(VAPOR,));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k27.unknown')
        self.assertEqual(g.snapshot(),before)

    def test_barkshield_triggers_after_payload_so_lethal_power_does_not_save_it(self):
        g=self.game(('k27.op.ping',),board=(BARK,));i=self.eid(g,BARK);self.op(g,'ping',i)
        self.power(g,i);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        g=self.game(board=(BARK,));self.power(g);self.assertEqual(self.entity(g,BARK).max_health,4);self.portable(g)

    def test_tortolla_gains_armor_and_attack_per_actual_damage_packet(self):
        g=self.game(('k27.op.all1','k27.op.all1'),board=(TORT,));self.op(g,'all1');self.op(g,'all1')
        self.assertEqual((self.entity(g,TORT).attack,self.entity(g,TORT).health,self.hero(g).armor),(3,28,2));self.portable(g)

    def test_dragonbane_uses_own_power_and_five_minion_ability_damage(self):
        g=self.game(board=(BANE,'TIME_856'));self.power(g)
        self.assertEqual(self.hero(g,2).health,24);self.assertEqual(g.state.players[1].mana,38);self.portable(g)

    def test_enemy_power_does_not_buff_or_awaken_owner_sources(self):
        g=self.game(board=(BARK,SLEEP,BANE),active=2);self.power(g,self.hero(g,2).id)
        self.assertEqual(self.entity(g,BARK).max_health,2);self.assertIsNotNone(self.entity(g,SLEEP).dormancy)
        self.assertEqual(self.hero(g,2).health,29)

    def test_sleeping_sprite_wakes_same_entity_without_new_summon_or_immediate_attack(self):
        g=self.game((SLEEP,));i=self.play(g,SLEEP);self.assertIsNotNone(g.state.entities[i].dormancy)
        self.power(g);self.assertIsNone(g.state.entities[i].dormancy)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(Attack(1,i,self.hero(g,2).id))
        self.assertEqual(g.snapshot(),before);self.end(g);self.end(g);g.apply(Attack(1,i,self.hero(g,2).id))
        self.assertEqual(sum(v.kind=='minion_summoned'for v in g.events),1);self.assertEqual(self.hero(g,2).health,26);self.portable(g)

    def test_old_awaken_request_cannot_wake_new_dormancy_instance(self):
        g=self.game(board=('k27.watch',SLEEP),mode='redormant');before=self.entity(g,SLEEP).dormancy.id;self.power(g)
        current=self.entity(g,SLEEP).dormancy;self.assertIsNotNone(current);self.assertNotEqual(current.id,before)
        self.assertEqual(sum(v.kind=='minion_awakened'for v in g.events),1);self.portable(g)

    def test_pending_captured_awaken_codec_restores_and_fault_choice_rolls_back(self):
        g=self.game(('k27.op.wake_choice',),board=(SLEEP,));self.op(g,'wake_choice');restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for branch in (g,restored):self.choose(branch);self.assertIsNone(self.entity(branch,SLEEP).dormancy)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_real_power_waiting_keeps_original_wake_and_can_restore(self):
        g=self.game(board=('k27.watch',SLEEP),mode='wait');self.power(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertIsNotNone(self.entity(g,SLEEP).dormancy);restored=self.portable(g)
        for branch in (g,restored):self.choose(branch);self.assertIsNone(self.entity(branch,SLEEP).dormancy)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_source_silence_stops_later_tidecaller_triggers(self):
        g=self.game(('k27.op.silence','CORE_EX1_506'),board=(TIDE,));self.op(g,'silence',self.eid(g,TIDE))
        self.play(g,'CORE_EX1_506');self.assertEqual(self.entity(g,TIDE).attack,1)

    def test_new_captured_awaken_rejects_malformed_clocks_and_public_queries_are_pure(self):
        g=self.game(board=(SLEEP,));entity=self.entity(g,SLEEP);ref=MinionReference.capture(entity)
        for clock in (True,0,-1,1.0,'1'):
            with self.subTest(clock=clock),self.assertRaises(ValueError):AwakenCapturedMinion(ref,clock)
        before=g.snapshot()
        for player in (1,2):
            public=json.dumps(g.observe(player))+json.dumps(g.for_player(player).legal_actions())
            for key in ('dormancy_id','reference','cast_history','death_history','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)
