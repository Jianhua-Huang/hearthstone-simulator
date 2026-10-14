"""M5-13d-02l-05e: four independent repeat families sharing one carrier.

Synthetic declarations test public composition, not official TIME_064 timing.
Every callback depends only on its RuleContext; fresh registries are equivalent.
"""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

from hs_sim.engine import (AddPlayerEffect, AppendageSpec, BattlecryRepeatSpec, CardClass,
    CardDefinition, CardMetadata, CardType, DeathrattleRepeatSpec, EndTurn,
    EndTurnRepeatSpec, EndTurnSpec, Game, HeroPowerRepeatSpec, Keyword,
    PlayCard, PlayerEffectSpec, PlayerSetup, Registry, RemovePlayerEffect, ResolutionError, ResolutionLimitExceeded,
    RewindSpec, Ruleset, Scenario, SelectChoice, SnapshotError, TriggerHeroPower,
    TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.battlecry_repeats import (GrantBattlecryRepeatAura,
    capture_plan as battlecry_plan)
from hs_sim.engine.battlecry_matching import capture_recipient
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.deathrattle_matching import capture_recipient_from_state
from hs_sim.engine.deathrattle_repeats import (GrantDeathrattleRepeatAura,
    capture_plan as deathrattle_plan)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, GainArmor, GrantDeathrattle, RandomDamage, RequestChoice,
    ReturnToHand, Silence, Summon, Transform, TriggerDeathrattles)
from hs_sim.engine.end_turn_repeats import (GrantEndTurnRepeatAura,
    capture_plan as end_turn_plan)
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.hero_power_repeats import (GrantHeroPowerRepeatAura,
    capture_plan as hero_power_plan)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import EndTurnRequest, EndTurnSelector, EndTurnSubject
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


FAMILIES = ('battlecry_repeat', 'deathrattle_repeat', 'hero_power_repeat', 'end_turn_repeat')


def declarations(counts=(2, 2, 2, 2)):
    return dict(battlecry_repeats=(BattlecryRepeatSpec(counts[0]),),
        deathrattle_repeats=(DeathrattleRepeatSpec(counts[1]),),
        hero_power_repeats=(HeroPowerRepeatSpec(counts[2]),),
        end_turn_repeats=(EndTurnRepeatSpec(counts[3]),))


def find(c, name, owner=None):
    player = c.player_id if owner is None else owner
    return next(i for i in c.state.players[player].board if c.state.entities[i].card_id == name)


def selected_end(c, name='end'):
    owner = c.player_id
    return TriggerEndTurnEffects(owner, EndTurnRequest(EndTurnSelector(
        'selected', (owner,), ('minion',), (find(c, name),))), c.source_id)


def choice(c):
    return RequestChoice(c.player_id, (
        ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),
        ChoiceOption('bad', 'bad', (TriggerHeroPower(c.player_id, 999999),))),
        source_id=c.source_id)


def nested_bodies(c, *, waiting=False):
    return [TriggerDeathrattles(find(c, 'rattle.wait' if waiting else 'rattle'), c.source_id),
        TriggerHeroPower(c.player_id, c.source_id, choices='player'),
        selected_end(c, 'end.wait' if waiting else 'end')]


def cascading(c, family, *, waiting=False, remove=False, add=False, failure=False):
    if family == 'battlecry': index = c.battlecry.repeat_index
    elif family == 'deathrattle': index = c.deathrattle.repeat_index
    elif family == 'hero_power': index = c.power_payload.repeat_index
    else: index = c.end_turn.repeat_index + 1
    if failure and index == 2:
        raise ValueError('mixed second position failed')
    out = [choice(c) if waiting else GainArmor(c.player_id, 1)]
    if index == 1 and remove: out.append(Silence(find(c, 'mixed')))
    if index == 1 and add: out.append(Summon(c.player_id, 'mixed'))
    if family == 'battlecry': out += nested_bodies(c, waiting=waiting)
    elif family == 'deathrattle':
        out += [TriggerHeroPower(c.player_id, c.source_id, choices='player'), selected_end(c)]
    elif family == 'hero_power':
        out += [TriggerDeathrattles(find(c, 'rattle'), c.source_id), selected_end(c)]
    else:
        out += [TriggerDeathrattles(find(c, 'rattle'), c.source_id),
            TriggerHeroPower(c.player_id, c.source_id, choices='player')]
    return out


def dr_proof_body(c, operation=None):
    if c.deathrattle.repeat_index == 2: return [choice(c)]
    out = [GainArmor(c.player_id,1)]
    if c.deathrattle.repeat_index == 1 and operation is not None:
        target=find(c,'mixed.three')
        out.insert(0,operation(target))
    return out


def fixture_registry():
    r = Registry('mixed-repeat-public-fixtures-v1')
    r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=1, health=8))
    r.register_card(CardDefinition('retainer', 'retainer', CardType.MINION, health=8,
        retain_rewind_outcomes=True))
    r.register_behavior('one', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('wait', lambda c: [choice(c)])
    r.register_behavior('silence.mixed',lambda c:[Silence(find(c,'mixed'))])
    r.register_behavior('window.read',lambda c:[GainArmor(c.player_id,
        10 if c.state.entities[find(c,'mixed')].silenced else 1)])
    r.register_behavior('bc.missing.wait',lambda c:[choice(c)])
    r.register_card(CardDefinition('bc.missing.wait','bc.missing.wait',CardType.MINION,
        health=8,on_play='silence.mixed',battlecry='bc.missing.wait'))
    r.register_behavior('transfer.mixed',lambda c:[ChangeControl(find(c,'mixed'),3-c.player_id)])
    r.register_card(CardDefinition('bc.transfer.wait','bc.transfer.wait',CardType.MINION,
        health=8,on_play='transfer.mixed',battlecry='wait'))
    r.register_behavior('dr.fatal',lambda c:[GainArmor(c.player_id,1)]
        if c.deathrattle.repeat_index==1 else [Damage(c.state.players[3-c.player_id].hero_id,30)])
    r.register_card(CardDefinition('dr.fatal','dr.fatal',CardType.MINION,health=8,deathrattle='dr.fatal'))
    r.register_behavior('end.fatal',lambda c:[TriggerDeathrattles(find(c,'dr.fatal'),c.source_id)])
    r.register_card(CardDefinition('end.fatal','end.fatal',CardType.MINION,health=8,
        triggers=(TriggerSpec('turn_ended','end.fatal',EndTurnSpec()),)))
    r.register_player_effect(PlayerEffectSpec('pe.dr','script.pe.install',kind='objective',
        duration=1,tick_event='turn_ended',deathrattle_repeats=(DeathrattleRepeatSpec(3),)))
    def remove_player_dr(c):
        if c.deathrattle.repeat_index==2: return [choice(c)]
        if c.deathrattle.repeat_index==1:
            instance=next(e for e in c.state.players[c.player_id].player_effects if e.spec_id=='pe.dr')
            return [RemovePlayerEffect(c.player_id,instance.id),GainArmor(c.player_id,1)]
        return [GainArmor(c.player_id,1)]
    r.register_behavior('dr.player',remove_player_dr)
    r.register_card(CardDefinition('dr.player','dr.player',CardType.MINION,health=8,deathrattle='dr.player'))
    r.register_behavior('end.pe',lambda c:[TriggerDeathrattles(find(c,'dr.proof.keep'),c.source_id)])
    r.register_card(CardDefinition('end.pe','end.pe',CardType.MINION,health=8,
        triggers=(TriggerSpec('turn_ended','end.pe',EndTurnSpec()),)))
    r.register_card(CardDefinition('bc.window','bc.window',CardType.MINION,health=8,
        on_play='silence.mixed',battlecry='window.read'))
    r.register_behavior('generic.wait.silence',lambda c:[RequestChoice(c.player_id,
        (ChoiceOption('one','one',(Silence(find(c,'mixed')),GainArmor(c.player_id,1))),),
        source_id=c.source_id)])
    r.register_card(CardDefinition('bc.generic.wait','bc.generic.wait',CardType.MINION,health=8,
        on_play='generic.wait.silence',battlecry='window.read'))
    r.register_card(CardDefinition('generic.only.wait','generic.only.wait',CardType.MINION,
        health=8,on_play='wait'))
    r.register_card(CardDefinition('commit.wait','commit.wait',CardType.MINION,health=8,
        triggers=(TriggerSpec('card_committed','wait'),)))
    r.register_behavior('colossal.entry.silence',lambda c:[Silence(c.event.source_id)]
        if c.state.entities[c.event.source_id].card_id=='colossal.wait' else [])
    r.register_card(CardDefinition('colossal.silencer','colossal.silencer',CardType.MINION,
        health=8,triggers=(TriggerSpec('minion_summoned','colossal.entry.silence'),)))
    r.register_card(CardDefinition('dr.window','dr.window',CardType.MINION,health=8,
        deathrattle='silence.mixed'))
    r.register_card(CardDefinition('hp.window','hp.window',CardType.HERO_POWER,on_use='window.read'))
    r.register_card(CardDefinition('hp.silencer','hp.silencer',CardType.MINION,health=8,
        triggers=(TriggerSpec('hero_power_started','silence.mixed'),)))
    r.register_card(CardDefinition('end.silencer','end.silencer',CardType.MINION,health=8,
        triggers=(TriggerSpec('turn_ended','silence.mixed',EndTurnSpec()),)))
    r.register_card(CardDefinition('end.window','end.window',CardType.MINION,health=8,
        triggers=(TriggerSpec('turn_ended','window.read',EndTurnSpec()),)))
    for name, counts in (('mixed', (2,2,2,2)), ('mixed.a', (2,3,4,2)),
            ('mixed.b', (3,2,2,4)), ('mixed.three', (3,3,3,3))):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=8,
            **declarations(counts)))
    narrow=declarations(); narrow['battlecry_repeats']=(BattlecryRepeatSpec(2,(CardType.MINION,)),)
    r.register_card(CardDefinition('mixed.bc.narrow','mixed.bc.narrow',CardType.MINION,
        attack=1,health=8,**narrow))
    r.register_card(CardDefinition('mixed.body', 'mixed.body', CardType.MINION, health=8,
        battlecry='one', deathrattle='one',
        triggers=(TriggerSpec('turn_ended', 'one', EndTurnSpec()),), **declarations()))
    r.register_card(CardDefinition('colossal.wait','colossal.wait',CardType.MINION,health=8,
        keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('mixed'),),battlecry='wait'))
    for name, fields in (('cry', dict(battlecry='one')),
            ('cry.wait', dict(battlecry='wait')), ('rattle', dict(deathrattle='one')),
            ('rattle.wait', dict(deathrattle='wait')),
            ('end', dict(triggers=(TriggerSpec('turn_ended', 'one', EndTurnSpec()),))),
            ('end.wait', dict(triggers=(TriggerSpec('turn_ended', 'wait', EndTurnSpec()),)))):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=8, **fields))
    for name, behavior in (('power', 'one'), ('power.wait', 'wait')):
        r.register_card(CardDefinition(name, name, CardType.HERO_POWER, cost=2, on_use=behavior))
    for mode, operation in (('keep',None),('silence',Silence),('return',ReturnToHand),
            ('destroy',Destroy),('transform',lambda i:Transform(i,'plain'))):
        name='dr.proof.'+mode
        r.register_behavior(name,lambda c,op=operation:dr_proof_body(c,op))
        r.register_card(CardDefinition(name,name,CardType.MINION,health=8,deathrattle=name))
    scripts = {
        'invoke.dr': lambda c: [TriggerDeathrattles(find(c, 'rattle'), c.source_id)],
        'invoke.end': lambda c: [selected_end(c)],
        'invoke.hp': lambda c: [TriggerHeroPower(c.player_id, c.source_id, choices='player')],
        'silence': lambda c: [Silence(c.state.players[c.player_id].board[0])],
        'destroy': lambda c: [Destroy(c.state.players[c.player_id].board[0])],
        'destroy.middle': lambda c: [Destroy(c.state.players[c.player_id].board[1])],
        'return': lambda c: [ReturnToHand(c.state.players[c.player_id].board[0])],
        'transform': lambda c: [Transform(c.state.players[c.player_id].board[0], 'plain')],
        'steal': lambda c: [ChangeControl(c.state.players[c.player_id].board[0], 3-c.player_id)],
        'sleep': lambda c: [MakeDormant(c.state.players[c.player_id].board[0], None)],
        'wake': lambda c: [AwakenMinion(c.state.players[c.player_id].board[0])],
        'copy': lambda c: [CopyMinion(c.state.players[c.player_id].board[0], c.player_id)],
        'copy.base': lambda c: [CopyMinion(c.state.players[c.player_id].board[0], c.player_id, mode='base')],
        'grant': lambda c: [effect(c.state.players[c.player_id].board[0], source_id=c.source_id)
            for effect in (GrantBattlecryRepeatAura, GrantDeathrattleRepeatAura,
                GrantHeroPowerRepeatAura, GrantEndTurnRepeatAura)],
        'grant.expiry': lambda c: [effect(c.state.players[c.player_id].board[0],
            source_id=c.source_id, expires_turn=c.state.turn)
            for effect in (GrantBattlecryRepeatAura, GrantDeathrattleRepeatAura,
                GrantHeroPowerRepeatAura, GrantEndTurnRepeatAura)],
        'kill.both': lambda c: [DamageBatch(tuple(Damage(i, 20, c.source_id)
            for i in c.state.players[c.player_id].board[:2]))],
        'dr.wait': lambda c: [TriggerDeathrattles(find(c, 'rattle.wait'), c.source_id)],
        'end.wait': lambda c: [selected_end(c, 'end.wait')],
        'dr.windows': lambda c: [GrantDeathrattle(find(c,'dr.window'),'window.read',c.source_id),
            TriggerDeathrattles(find(c,'dr.window'),c.source_id)],
        'dr.proof': lambda c:[TriggerDeathrattles(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id.startswith('dr.proof.')),c.source_id)],
        'dr.proof.fixed': lambda c:[TriggerDeathrattles(find(c,'dr.proof.keep'),c.source_id,times=2)],
        'pe.install': lambda c:[AddPlayerEffect(c.player_id,'pe.dr',c.source_id)],
        'pe.invoke': lambda c:[TriggerDeathrattles(find(c,'dr.player'),c.source_id)],
        'bc.finite': lambda c:[AddBattlecryRepeatModifier(c.player_id,BattlecryRepeatSpec(3),
            c.source_id,uses=1)],
        'bc.persistent': lambda c:[AddBattlecryRepeatModifier(c.player_id,BattlecryRepeatSpec(2),
            c.source_id)],
        'bc.two.uses': lambda c:[AddBattlecryRepeatModifier(c.player_id,BattlecryRepeatSpec(2),
            c.source_id,uses=2)],
    }
    for name, callback in scripts.items():
        behavior = 'script.'+name
        r.register_behavior(behavior, callback)
        r.register_card(CardDefinition('script.'+name, name, CardType.SPELL, on_play=behavior))
    for family in ('battlecry', 'deathrattle', 'hero_power', 'end_turn'):
        for mode in ('remove', 'add', 'fail'):
            name = family+'.'+mode
            r.register_behavior(name, lambda c, f=family, m=mode: cascading(c, f,
                remove=m=='remove', add=m=='add', failure=m=='fail'))
            if family == 'hero_power':
                fields = dict(on_use=name); kind = CardType.HERO_POWER
            elif family == 'end_turn':
                fields = dict(triggers=(TriggerSpec('turn_ended', name, EndTurnSpec()),)); kind=CardType.MINION
            else: fields = {family:name}; kind=CardType.MINION
            r.register_card(CardDefinition(name, name, kind, health=8 if kind==CardType.MINION else 0,
                cost=2 if kind==CardType.HERO_POWER else 0, **fields))
    r.register_behavior('cascade.wait', lambda c: cascading(c, 'battlecry', waiting=True))
    r.register_card(CardDefinition('cascade.wait', 'cascade.wait', CardType.MINION,
        health=8, battlecry='cascade.wait'))
    def fail_after_random(c):
        if c.battlecry.repeat_index==2: raise ValueError('mixed random branch failed')
        return [RandomDamage((c.state.players[2].hero_id,*c.state.players[2].board),1,c.source_id),
            *nested_bodies(c)]
    r.register_behavior('battlecry.fail.random',fail_after_random)
    r.register_card(CardDefinition('battlecry.fail.random','battlecry.fail.random',CardType.MINION,
        health=8,battlecry='battlecry.fail.random'))
    r.register_behavior('rewind.mixed', lambda c: [Silence(find(c, 'mixed'))]
        if any(c.state.entities[i].card_id=='mixed' and not c.state.entities[i].silenced
            for i in c.state.players[c.player_id].board) else nested_bodies(c))
    r.register_behavior('rewind.power.body', lambda c: [Silence(find(c, 'mixed'))]
        if any(c.state.entities[i].card_id=='mixed' and not c.state.entities[i].silenced
            for i in c.state.players[c.player_id].board) else
        [TriggerDeathrattles(find(c,'rattle'),c.source_id),selected_end(c)])
    for name, kind in (('rewind.cry', CardType.MINION), ('rewind.power', CardType.HERO_POWER)):
        r.register_card(CardDefinition(name, name, kind, health=8 if kind==CardType.MINION else 0,
            cost=2, keywords=(Keyword.REWIND,), rewind=RewindSpec(1),
            **({'battlecry':'rewind.mixed'} if kind==CardType.MINION else {'on_use':'rewind.power.body'})))
    mech = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))
    r.register_card(CardDefinition('mech', 'mech', CardType.MINION, health=8, metadata=mech))
    r.register_card(CardDefinition('mixed.magnetic', 'mixed.magnetic', CardType.MINION,
        health=8, keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',), metadata=mech,
        **declarations()))
    return r


class MixedRepeatTests(unittest.TestCase):
    def setUp(self): self.r = fixture_registry()

    def game(self, board=('mixed','rattle','end'), hand=('cry','script.invoke.dr','script.invoke.end'),
            enemy=(), power='power', rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',)*12, mana=10,
                max_mana=10, hero_power_card_id=power),
            PlayerSetup('hero', hand=('cry',), board=enemy, deck=('plain',)*12, mana=10,
                max_mana=10, hero_power_card_id='power')), seed=148), self.r, ruleset=rules)

    def play(self, g, name, *, position=None):
        owner=g.state.active_player
        entity=next(i for i in g.state.players[owner].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(owner,entity,position=position)); return entity

    def choose(self, g, option='one'):
        pending=g.state.pending_choice
        g.apply(SelectChoice(pending.player_id,pending.id,(option,)))

    def armor(self, g, owner=1): return g.state.entities[g.state.players[owner].hero_id].armor
    def first(self, g, owner=1): return g.state.entities[g.state.players[owner].board[0]]
    def use(self,g): g.apply(UseHeroPower(g.state.active_player,
        g.state.players[g.state.active_player].hero_power_id))

    def check(self,g,*,fresh=True):
        self.assertEqual(g.state.next_deathrattle_id,len(g.state.deathrattle_history)+1)
        snapshot=json.loads(json.dumps(g.snapshot()))
        registry=fixture_registry() if fresh else self.r
        self.assertEqual(Game.from_snapshot(snapshot,registry).snapshot(),snapshot)
        self.assertEqual(g.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(g),registry).snapshot(),snapshot)

    def named(self,value,suffix):
        found=[]
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+suffix): found.append(value)
            for child in value.values(): found.extend(self.named(child,suffix))
        elif isinstance(value,list):
            for child in value: found.extend(self.named(child,suffix))
        return found

    def reject(self,snapshot):
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot,fixture_registry())
        self.assertNotIn('digest mismatch',str(error.exception))

    def waiting_dr_proof(self,mode='keep'):
        g=self.game(board=('mixed.three','dr.proof.'+mode,'end'),hand=('script.dr.proof',))
        self.play(g,'script.dr.proof'); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([r.capture.repeat_index for r in g.state.deathrattle_history],[1,2,3])
        return g

    def shrink_dr_tail(self,snapshot):
        """Synchronize every old local ledger; preserve physical source and events.

        This used to pass because a running extra had no remaining first Invoke
        from which to recover the original complete acceptance window.
        """
        def shrink(value):
            if isinstance(value,dict):
                if 'deathrattle_history' in value and 'deathrattle_batches' in value:
                    rows=value['deathrattle_history']
                    if isinstance(rows,dict): rows=rows['list']
                    rows[:]=[row for row in rows if
                        (row.get('fields',row)['capture'].get('fields',row.get('fields',row)['capture'])['id']<3)]
                    # Keep the cropped allocation ledger internally balanced:
                    # these negatives must exercise original acceptance proof,
                    # independently of the separate whole-ledger counter gate.
                    value['next_deathrattle_id']=len(rows)+1
                if 'repetitions' in value and 'contributors' in value:
                    value['repetitions']=2
                    contributors=value['contributors']
                    if isinstance(contributors,dict): contributors=contributors.get('tuple',contributors.get('list',[]))
                    for contributor in contributors:
                        fields=contributor.get('fields',contributor)
                        ability=fields.get('ability')
                        if ability is not None:
                            ability=ability.get('fields',ability)
                            spec=ability.get('deathrattle_repeat')
                            if spec is not None: spec.get('fields',spec)['repetitions']=2
                if 'tuple' in value:
                    value['tuple'][:]=[work for work in value['tuple'] if not
                        (isinstance(work,dict) and work.get('type','').endswith('.InvokeDeathrattle')
                         and work['fields']['context']['fields']['deathrattle']['fields']['id']==3)]
                for child in value.values(): shrink(child)
            elif isinstance(value,list):
                for child in value: shrink(child)
        shrink(snapshot)
        return snapshot

    def live_plans(self,g,owner=1):
        victim=next(g.state.entities[i] for i in g.state.players[owner].board
            if g.state.entities[i].card_id in ('rattle','rattle.wait'))
        body=next(g.state.entities[i] for i in g.state.players[owner].board
            if g.state.entities[i].card_id in ('end','end.wait'))
        subject=EndTurnSubject(body.id,owner,body.card_id,body.entered_order,body.zone_epoch,
            ability=active_abilities(body,'trigger')[0])
        return (battlecry_plan(SimpleNamespace(state=g.state,rules=g.ruleset,registry=self.r),owner,capture_recipient(g.state,self.r,victim.id)),
            deathrattle_plan(g.state,self.r,owner,capture_recipient_from_state(g.state,self.r,victim.id),
                active_abilities(victim,'deathrattle')[0]),
            hero_power_plan(g.state,self.r,owner),end_turn_plan(g.state,self.r,subject))

    def counts(self,g): return tuple(p.repetitions for p in self.live_plans(g))
    def execute_four(self,g):
        self.play(g,'cry'); self.use(g); self.play(g,'script.invoke.dr'); self.play(g,'script.invoke.end')
        return (g.state.battlecry_batches[-1].plan.repetitions,
            g.state.deathrattle_batches[-1].plan.repetitions,
            g.state.hero_power_history[-1].repeat_plan.repetitions,
            g.state.end_turn_batches[-1].plans[0].repetitions)

    def test_four_printed_declarations_have_separate_attachment_identity(self):
        g=self.game(); carrier=self.first(g)
        self.assertCountEqual([a.kind for a in carrier.abilities],FAMILIES)
        self.assertEqual(len({a.id for a in carrier.abilities}),4)
        self.assertTrue(all(a.origin=='printed' and a.source_id==carrier.id for a in carrier.abilities))
        self.assertEqual(self.counts(g),(2,2,2,2)); self.check(g)

    def test_repeat_declarations_alone_are_not_effect_bodies(self):
        g=self.game(board=('mixed',),hand=('mixed','script.destroy'))
        self.play(g,'mixed'); self.assertFalse(g.state.battlecry_history)
        g.apply(EndTurn(1)); self.assertFalse(g.state.end_turn_history)
        g.apply(EndTurn(2)); self.play(g,'script.destroy')
        self.assertFalse(g.state.deathrattle_history); self.assertEqual(self.armor(g),0); self.check(g)

    def test_four_real_activations_keep_separate_roots_and_once_only_payments(self):
        g=self.game(); self.assertEqual(self.execute_four(g),(2,2,2,2))
        self.assertEqual(self.armor(g),8); self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len(g.state.hero_power_history),1)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn,1)
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind=='turn_ended' for e in g.events)); self.check(g)

    def test_two_identical_mixed_sources_keep_two_each_without_product(self):
        g=self.game(board=('mixed','mixed','rattle','end'))
        self.assertEqual(self.execute_four(g),(2,2,2,2)); self.assertEqual(self.armor(g),8)
        self.assertEqual([len(p.contributors) for p in self.live_plans(g)],[2]*4); self.check(g)

    def test_asymmetric_sources_max_is_calculated_independently_for_each_family(self):
        g=self.game(board=('mixed.a','mixed.b','rattle','end'))
        self.assertEqual(self.execute_four(g),(3,3,4,4)); self.assertEqual(self.armor(g),14)
        self.assertEqual([len(p.contributors) for p in self.live_plans(g)],[2]*4); self.check(g)

    def test_sole_enemy_mixed_source_contributes_to_no_friendly_family(self):
        g=self.game(board=('rattle','end'),enemy=('mixed',))
        self.assertEqual(self.execute_four(g),(1,1,1,1)); self.assertEqual(self.armor(g),4); self.check(g)

    def test_single_silence_revokes_all_four_until_another_carrier_contributes(self):
        g=self.game(hand=('script.silence',)); self.play(g,'script.silence')
        self.assertEqual(self.counts(g),(1,1,1,1)); self.assertFalse(self.first(g).abilities); self.check(g)

    def test_single_transform_replaces_all_four_with_current_printed_definition(self):
        g=self.game(hand=('script.transform',)); identity=self.first(g).id
        self.play(g,'script.transform')
        self.assertEqual((self.first(g).id,self.first(g).card_id),(identity,'plain'))
        self.assertEqual(self.counts(g),(1,1,1,1)); self.check(g)

    def test_single_dormancy_disables_and_awaken_reactivates_every_family(self):
        g=self.game(hand=('script.sleep','script.wake')); ids=[a.id for a in self.first(g).abilities]
        self.play(g,'script.sleep'); self.assertEqual(self.counts(g),(1,1,1,1))
        self.play(g,'script.wake'); self.assertEqual(self.counts(g),(2,2,2,2))
        self.assertEqual([a.id for a in self.first(g).abilities],ids); self.check(g)

    def test_control_transfer_moves_all_four_source_policies_as_one_carrier(self):
        g=self.game(hand=('script.steal',),enemy=('rattle','end'))
        identity=self.first(g).id; self.play(g,'script.steal')
        self.assertEqual(self.counts(g),(1,1,1,1))
        self.assertEqual(tuple(p.repetitions for p in self.live_plans(g,2)),(2,2,2,2))
        self.assertEqual(g.state.entities[identity].controller,2); self.check(g)

    def test_return_and_replay_reset_shared_ids_then_reinstall_four_printed_sources(self):
        g=self.game(hand=('script.return',)); before=self.first(g); ids={a.id for a in before.abilities}
        identity=before.id; self.play(g,'script.return'); self.assertEqual(self.counts(g),(1,1,1,1))
        self.play(g,'mixed'); self.assertEqual(self.counts(g),(2,2,2,2))
        self.assertEqual(g.state.entities[identity].zone,Zone.BOARD)
        self.assertTrue(ids.isdisjoint(a.id for a in g.state.entities[identity].abilities)); self.check(g)

    def test_full_copy_rebases_all_four_ids_and_preserves_each_printed_provenance(self):
        g=self.game(hand=('script.copy',)); old=self.first(g); self.play(g,'script.copy')
        clone=g.state.entities[g.state.players[1].board[-1]]
        self.assertCountEqual([a.kind for a in clone.abilities],FAMILIES)
        self.assertTrue(set(a.id for a in old.abilities).isdisjoint(a.id for a in clone.abilities))
        self.assertEqual([a.source_id for a in clone.abilities],[old.id]*4)
        self.assertEqual([len(p.contributors) for p in self.live_plans(g)],[2]*4); self.check(g)

    def test_copied_four_policies_survive_silencing_original_but_do_not_multiply(self):
        g=self.game(hand=('script.copy','script.silence')); self.play(g,'script.copy'); self.play(g,'script.silence')
        self.assertEqual(self.counts(g),(2,2,2,2))
        self.assertEqual([len(p.contributors) for p in self.live_plans(g)],[1]*4); self.check(g)

    def test_dynamic_four_grants_share_source_but_have_independent_ids(self):
        g=self.game(board=('plain','rattle','end'),hand=('script.grant',))
        origin=self.play(g,'script.grant'); abilities=self.first(g).abilities
        self.assertCountEqual([a.kind for a in abilities],FAMILIES)
        self.assertEqual(len({a.id for a in abilities}),4)
        self.assertTrue(all(a.source_id==origin and a.origin=='granted' for a in abilities))
        self.assertEqual(self.counts(g),(2,2,2,2)); self.check(g)

    def test_full_copy_preserves_all_grants_while_base_copy_keeps_only_printed_base(self):
        g=self.game(board=('plain','rattle','end'),hand=('script.grant','script.copy','script.copy.base'))
        self.play(g,'script.grant'); self.play(g,'script.copy'); self.play(g,'script.copy.base')
        full,base=(g.state.entities[i] for i in g.state.players[1].board[-2:])
        self.assertCountEqual([a.kind for a in full.abilities],FAMILIES); self.assertFalse(base.abilities)
        self.assertEqual([len(p.contributors) for p in self.live_plans(g)],[2]*4); self.check(g)

    def test_all_four_dynamic_grants_expire_on_same_real_boundary(self):
        g=self.game(board=('plain','rattle','end'),hand=('script.grant.expiry',))
        self.play(g,'script.grant.expiry'); self.assertEqual(self.counts(g),(2,2,2,2))
        g.apply(EndTurn(1)); self.assertEqual(self.armor(g),2)
        self.assertEqual(self.counts(g),(1,1,1,1)); self.assertFalse(self.first(g).abilities); self.check(g)

    def test_one_magnetic_component_transfers_all_four_policies_to_same_host(self):
        g=self.game(board=('mech','rattle','end'),hand=('mixed.magnetic',))
        host=self.first(g).id; origin=self.play(g,'mixed.magnetic',position=0)
        abilities=[a for a in g.state.entities[host].abilities if a.kind in FAMILIES]
        self.assertCountEqual([a.kind for a in abilities],FAMILIES)
        self.assertTrue(all(a.source_id==origin and a.magnetic_id==1 for a in abilities))
        self.assertEqual(self.counts(g),(2,2,2,2)); self.check(g)

    def test_source_and_victim_simultaneous_death_do_not_cross_freeze_pre_removal(self):
        g=self.game(hand=('script.kill.both',)); self.play(g,'script.kill.both')
        self.assertEqual(len(g.state.death_history),2)
        self.assertEqual(g.state.deathrattle_batches[-1].plan.repetitions,1)
        self.assertEqual(self.armor(g),1)
        self.assertEqual(g.state.hero_power_history,[]); self.assertEqual(g.state.end_turn_history,[]); self.check(g)

    def test_body_owns_repeat_policies_but_natural_death_cannot_use_removed_friendly_aura(self):
        g=self.game(board=('rattle','end'),hand=('mixed.body','script.destroy'))
        identity=self.play(g,'mixed.body'); self.assertEqual(g.state.battlecry_batches[-1].plan.repetitions,2)
        g.apply(EndTurn(1)); self.assertEqual(len(g.state.end_turn_history),4)
        g.apply(EndTurn(2))
        # Kill the mixed carrier, preserving another ordinary rattle as unrelated.
        self.check(g)
        self.r = fixture_registry()
        h=self.game(board=('mixed.body','rattle','end'),hand=('script.destroy',))
        self.play(h,'script.destroy')
        self.assertEqual(h.state.deathrattle_batches[-1].plan.repetitions,1)
        self.assertEqual(self.armor(h),1); self.check(h)

    def test_battlecry_frozen_twice_other_families_accept_after_its_source_silence(self):
        g=self.game(hand=('battlecry.remove',)); self.play(g,'battlecry.remove')
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,2)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history],[1,1])
        self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[1,1])
        self.assertEqual([b.plans[0].repetitions for b in g.state.end_turn_batches],[1,1])
        self.assertEqual(self.armor(g),8); self.check(g)

    def test_deathrattle_frozen_twice_power_and_end_accept_after_source_silence(self):
        g=self.game(board=('mixed','deathrattle.remove','end'),hand=('script.destroy.middle',))
        self.play(g,'script.destroy.middle')
        self.assertEqual(g.state.deathrattle_batches[0].plan.repetitions,2)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history],[1,1])
        self.assertEqual([b.plans[0].repetitions for b in g.state.end_turn_batches],[1,1]); self.check(g)

    def test_power_frozen_twice_dr_and_end_accept_after_its_source_silence(self):
        g=self.game(power='hero_power.remove',hand=()); self.use(g)
        self.assertEqual(g.state.hero_power_history[0].repeat_plan.repetitions,2)
        self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[1,1])
        self.assertEqual([b.plans[0].repetitions for b in g.state.end_turn_batches],[1,1])
        self.assertEqual(self.armor(g),6); self.check(g)

    def test_end_frozen_twice_dr_and_power_accept_after_its_source_silence(self):
        g=self.game(board=('mixed','rattle','end_turn.remove'),hand=())
        g.apply(EndTurn(1))
        self.assertEqual(g.state.end_turn_batches[0].plans[0].repetitions,2)
        self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[1,1])
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history],[1,1])
        self.assertEqual(self.armor(g),6); self.assertEqual(sum(e.kind=='turn_ended' for e in g.events),1); self.check(g)

    def test_battlecry_accepts_once_then_new_source_repeats_later_other_families(self):
        g=self.game(board=('rattle','end'),hand=('battlecry.add',)); self.play(g,'battlecry.add')
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,1)
        self.assertEqual(g.state.deathrattle_batches[0].plan.repetitions,2)
        self.assertEqual(g.state.hero_power_history[0].repeat_plan.repetitions,2)
        self.assertEqual(g.state.end_turn_batches[0].plans[0].repetitions,2)
        self.assertEqual(self.armor(g),7); self.check(g)

    def test_first_battlecry_reads_actual_begin_state_after_generic_body_but_plan_stays_frozen(self):
        g=self.game(hand=('bc.window',)); self.play(g,'bc.window')
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,2)
        self.assertEqual(self.armor(g),20)
        self.assertEqual(self.counts(g),(1,1,1,1)); self.check(g)

    def test_mixed_bc_original_acceptance_restores_during_generic_choice_before_any_batch_starts(self):
        g=self.game(hand=('bc.generic.wait',)); self.play(g,'bc.generic.wait')
        self.assertEqual(g.state.battlecry_batches,[]); self.assertEqual(g.state.battlecry_history,[])
        self.check(g); restored=Game.from_snapshot(g.snapshot(),fixture_registry())
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,2)
        self.assertEqual(self.counts(g),(1,1,1,1)); self.assertEqual(self.armor(g),21); self.check(g)

    def test_pre_battlecry_original_proof_cannot_stand_in_for_a_deleted_entire_queued_root(self):
        g=self.game(hand=('bc.generic.wait',)); self.play(g,'bc.generic.wait'); snapshot=g.snapshot()
        queue=snapshot['resolution_frame']['fields']['continuation']['tuple']
        starts=[work for work in queue if work.get('type','').endswith('.BeginBattlecryBatch')]
        self.assertEqual(len(starts),1); queue.remove(starts[0])
        self.reject(snapshot)

    def test_pre_battlecry_durable_obligation_survives_removing_all_queued_root_and_all_proofs(self):
        for null_receipt in (False,True):
            with self.subTest(null_receipt=null_receipt):
                self.r=fixture_registry(); g=self.game(hand=('bc.generic.wait',)); self.play(g,'bc.generic.wait')
                snapshot=g.snapshot(); queue=snapshot['resolution_frame']['fields']['continuation']['tuple']
                removed=[work for work in queue if work.get('type','').endswith(
                    ('.BeginBattlecryBatch','.FinishBattlecryAcceptance'))]
                self.assertEqual(len(removed),2)
                for work in removed: queue.remove(work)
                if null_receipt: snapshot['state']['play_history'][0]['battlecry_acceptance']=None
                self.reject(snapshot)

    def test_battlecry_receipt_explicit_wire_field_cannot_be_omitted_or_nulled_after_acceptance(self):
        for mode in ('missing','null'):
            with self.subTest(mode=mode):
                self.r=fixture_registry(); g=self.game(hand=('bc.generic.wait',)); self.play(g,'bc.generic.wait')
                snapshot=g.snapshot(); record=snapshot['state']['play_history'][0]
                self.assertIsNotNone(record['battlecry_acceptance'])
                if mode=='missing': record.pop('battlecry_acceptance')
                else: record['battlecry_acceptance']=None
                self.reject(snapshot)

    def test_generic_body_without_battlecry_has_explicit_empty_receipt_and_needs_no_bc_proof(self):
        g=self.game(hand=('generic.only.wait',)); self.play(g,'generic.only.wait')
        receipt=g.snapshot()['state']['play_history'][0]['battlecry_acceptance']
        self.assertEqual(receipt['payloads'],[]); self.assertIsNone(receipt['plan'])
        self.assertEqual(self.named(g.snapshot()['resolution_frame'],'FinishBattlecryAcceptance'),[])
        self.check(g); self.choose(g); self.assertEqual(self.armor(g),1)
        self.assertEqual(g.state.battlecry_history,[]); self.check(g)

    def test_colossal_silenced_before_delayed_actual_acceptance_can_record_empty_body_receipt(self):
        g=self.game(board=('mixed','rattle','end','colossal.silencer'),hand=('colossal.wait',))
        self.play(g,'colossal.wait'); self.assertIsNone(g.state.pending_choice)
        receipt=g.snapshot()['state']['play_history'][0]['battlecry_acceptance']
        self.assertEqual(receipt['payloads'],[]); self.assertIsNone(receipt['plan'])
        self.assertEqual(g.state.battlecry_history,[]); self.assertEqual(self.armor(g),0); self.check(g)

    def test_true_commit_wait_before_payload_acceptance_can_keep_none_receipt(self):
        g=self.game(board=('mixed','rattle','end','commit.wait'),hand=('cry',)); self.play(g,'cry')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertIsNone(g.snapshot()['state']['play_history'][0]['battlecry_acceptance'])
        self.check(g); self.choose(g); self.assertEqual(self.armor(g),3)
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,2); self.check(g)

    def test_first_dr_of_second_ability_keeps_capture_window_extra_reads_new_silenced_source(self):
        g=self.game(board=('mixed','dr.window','end'),hand=('script.dr.windows',))
        self.play(g,'script.dr.windows')
        self.assertEqual(g.state.deathrattle_batches[0].plan.repetitions,2)
        self.assertEqual(self.armor(g),11)
        self.assertEqual([x.capture.repeat_index for x in g.state.deathrattle_history],[1,2,1,2])
        self.check(g)

    def test_first_power_keeps_root_window_while_extra_reads_started_reaction_source_change(self):
        g=self.game(board=('mixed','rattle','end','hp.silencer'),hand=(),power='hp.window')
        self.use(g); self.assertEqual(g.state.hero_power_history[0].repeat_plan.repetitions,2)
        self.assertEqual(self.armor(g),11); self.check(g)

    def test_first_end_second_body_keeps_original_window_extra_reads_source_change(self):
        g=self.game(board=('mixed','end.silencer','end.window'),hand=())
        g.apply(EndTurn(1)); self.assertEqual([p.repetitions for p in g.state.end_turn_batches[0].plans],[2,2])
        self.assertEqual(self.armor(g),11); self.check(g)

    def test_nested_four_family_waiting_positions_restore_with_fresh_registry(self):
        g=self.game(board=('mixed','rattle.wait','end.wait'),hand=('cascade.wait',),power='power.wait')
        self.play(g,'cascade.wait'); positions=0
        while g.state.pending_choice is not None:
            snapshot=json.loads(json.dumps(g.snapshot()))
            restored=Game.from_snapshot(snapshot,fixture_registry())
            self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(),restored.snapshot()); positions+=1
        self.assertEqual(positions,14); self.assertEqual(self.armor(g),14)
        self.assertEqual((len(g.state.battlecry_history),len(g.state.deathrattle_history),
            len(g.state.hero_power_payload_history),len(g.state.end_turn_history)),(2,4,4,4))
        self.check(g)

    def test_failure_in_a_nested_pending_choice_rolls_back_only_new_choice_action(self):
        g=self.game(board=('mixed','rattle.wait','end.wait'),hand=('cascade.wait',),power='power.wait')
        self.play(g,'cascade.wait'); self.choose(g); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        while g.state.pending_choice: self.choose(g)
        self.assertEqual(self.armor(g),14); self.check(g)

    def test_second_outer_position_failure_rolls_back_all_three_nested_family_roots(self):
        g=self.game(hand=('battlecry.fail',)); before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'mixed second position failed'):
            self.play(g,'battlecry.fail')
        self.assertEqual(g.snapshot(),before)
        self.assertFalse(g.state.battlecry_history or g.state.deathrattle_history or
            g.state.hero_power_history or g.state.end_turn_history)

    def test_engine_budget_failure_rolls_back_mixed_chain_instead_of_partial_game_result(self):
        g=self.game(hand=('battlecry.add',),rules=Ruleset(max_resolution_steps=20)); before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.play(g,'battlecry.add')
        self.assertEqual(g.snapshot(),before); self.assertEqual(g.state.status,'playing')

    def test_retained_battlecry_outcomes_keep_original_plan_other_roots_capture_current_source(self):
        g=self.game(board=('mixed','rattle','end','retainer'),hand=('rewind.cry',))
        self.play(g,'rewind.cry')
        self.assertEqual([(r.iteration,r.repeat_index) for r in g.state.battlecry_history],
            [(1,1),(1,2),(2,1),(2,2)])
        self.assertTrue(all(b.plan.repetitions==2 for b in g.state.battlecry_batches))
        self.assertTrue(all(p.repeat_plan.repetitions==1 for p in g.state.hero_power_history))
        self.assertEqual(len(g.state.hero_power_history),3); self.assertEqual(self.armor(g),9); self.check(g)

    def test_retained_power_outcomes_keep_original_plan_while_child_dr_and_end_recapture(self):
        g=self.game(board=('mixed','rattle','end','retainer'),hand=(),power='rewind.power'); self.use(g)
        self.assertEqual([(r.capture.iteration,r.capture.repeat_index)
            for r in g.state.hero_power_payload_history],[(1,1),(1,2),(2,1),(2,2)])
        self.assertTrue(all(b.plan.repetitions==2 for b in g.state.hero_power_payload_batches))
        # First position silences; later positions independently use all child families.
        self.assertTrue(all(b.plan.repetitions==1 for b in g.state.deathrattle_batches))
        self.assertTrue(all(b.plans[0].repetitions==1 for b in g.state.end_turn_batches)); self.check(g)

    def test_normal_rewind_abandons_all_cross_family_histories_and_retry_uses_checkpoint_source(self):
        g=self.game(hand=('rewind.cry',)); self.play(g,'rewind.cry')
        self.assertIsNotNone(g.state.pending_choice); self.choose(g,'retry')
        self.assertEqual(len(g.state.battlecry_batches),1)
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,2)
        self.assertEqual(len(g.state.hero_power_history),1)
        self.assertEqual(len(g.state.deathrattle_batches),1)
        self.assertEqual(len(g.state.end_turn_batches),1); self.check(g)

    def test_waiting_mixed_histories_and_attachment_sources_do_not_enter_player_dto(self):
        g=self.game(board=('mixed','rattle.wait','end.wait'),hand=('cascade.wait',),power='power.wait')
        self.play(g,'cascade.wait'); self.choose(g)
        for viewer in (1,2):
            text=json.dumps((g.observe(viewer),g.player_events(viewer),g.for_player(viewer).legal_actions()))
            for private in ('battlecry_batches','deathrattle_batches','hero_power_payload_history',
                    'end_turn_batches','contributors','repeat_plan','repeat_index','producer_mode',
                    'FinishEndTurnBatch','FinishHeroPower','battlecry_acceptance','next_deathrattle_id'):
                self.assertNotIn(private,text)
        self.check(g)

    def test_dr_last_extra_joint_shrink_rejected_with_all_four_original_source_specs_present(self):
        g=self.waiting_dr_proof(); corrupt=self.shrink_dr_tail(g.snapshot())
        self.reject(corrupt)
        self.choose(g); self.assertEqual(self.armor(g),3); self.check(g)

    def test_dr_last_extra_complete_acceptance_survives_all_shared_source_lifecycle_removals(self):
        for mode in ('silence','return','transform','destroy'):
            with self.subTest(mode=mode):
                self.r=fixture_registry(); g=self.waiting_dr_proof(mode)
                self.reject(self.shrink_dr_tail(g.snapshot()))
                self.choose(g); self.assertEqual(self.armor(g),3); self.check(g)

    def test_dr_last_extra_requires_whole_batch_finish_proof_even_without_surviving_source(self):
        g=self.waiting_dr_proof('silence'); snapshot=g.snapshot()
        queue=snapshot['resolution_frame']['fields']['continuation']['tuple']
        closers=[work for work in queue if work.get('type','').endswith('.FinishDeathrattleBatch')]
        self.assertEqual(len(closers),1)
        queue.remove(closers[0]); self.reject(snapshot)

    def test_dr_monotone_allocation_counter_rejects_deleted_entire_effect_ledger_and_all_controls(self):
        g=self.waiting_dr_proof('silence'); snapshot=g.snapshot()
        expected=len(g.state.deathrattle_history)+1
        self.assertEqual(snapshot['state']['next_deathrattle_id'],expected)
        def clear(value):
            if isinstance(value,dict):
                if 'deathrattle_history' in value and 'deathrattle_batches' in value:
                    for field in ('deathrattle_history','deathrattle_batches'):
                        rows=value[field]
                        if isinstance(rows,dict): rows=rows['list']
                        rows.clear()
                if 'tuple' in value:
                    value['tuple'][:]=[w for w in value['tuple'] if not
                        (isinstance(w,dict) and w.get('type','').endswith(
                            ('.InvokeDeathrattle','.FinishDeathrattle','.FinishDeathrattleBatch')))]
                for child in value.values(): clear(child)
            elif isinstance(value,list):
                for child in value: clear(child)
        clear(snapshot); self.assertEqual(snapshot['state']['next_deathrattle_id'],expected)
        self.reject(snapshot)

    def test_dr_allocation_counter_is_mandatory_strict_integer_and_exact_history_successor(self):
        for mode in ('missing','bool','behind','ahead'):
            with self.subTest(mode=mode):
                self.r=fixture_registry(); g=self.waiting_dr_proof(); snapshot=g.snapshot()
                if mode=='missing': snapshot['state'].pop('next_deathrattle_id')
                else: snapshot['state']['next_deathrattle_id']={
                    'bool':True,'behind':len(g.state.deathrattle_history),
                    'ahead':len(g.state.deathrattle_history)+2}[mode]
                self.reject(snapshot)

    def test_dr_fixed_outer_rounds_and_inner_repeats_share_original_proof_but_keep_two_axes(self):
        g=self.game(board=('mixed.three','dr.proof.keep','end'),hand=('script.dr.proof.fixed',))
        self.play(g,'script.dr.proof.fixed'); pauses=0
        while g.state.pending_choice:
            self.check(g); self.choose(g); pauses+=1
        self.assertEqual(pauses,2); self.assertEqual(self.armor(g),6)
        self.assertEqual([(r.capture.trigger_index,r.capture.repeat_index)
            for r in g.state.deathrattle_history],[(1,1),(1,2),(1,3),(2,1),(2,2),(2,3)])
        self.check(g)

    def test_battlecry_pending_count_cannot_be_spoofed_by_same_carrier_power_policy_id(self):
        g=self.game(hand=('cry.wait',)); self.play(g,'cry.wait')
        snapshot=g.snapshot(); carrier=self.first(g)
        power_id=active_abilities(carrier,'hero_power_repeat')[0].id
        plan=snapshot['state']['battlecry_batches'][0]['plan']
        plan['repetitions']=3; plan['contributors']=[power_id]
        self.reject(snapshot)

    def test_battlecry_pending_missing_source_cannot_turn_frozen_max_two_into_three(self):
        # Generic body erases all four policies after their common acceptance.
        g=self.game(hand=('bc.missing.wait',)); self.play(g,'bc.missing.wait')
        snapshot=g.snapshot(); snapshot['state']['battlecry_batches'][0]['plan']['repetitions']=3
        self.reject(snapshot)

    def test_surviving_same_id_board_bc_source_keeps_complete_immutable_scope_and_provenance(self):
        for mode in ('kinds.trim','kinds.expand','origin','source','expiry','silence.policy','carrier'):
            with self.subTest(mode=mode):
                self.r=fixture_registry(); source='mixed.bc.narrow' if mode=='kinds.expand' else 'mixed'
                g=self.game(board=(source,'rattle','end'),hand=('cry.wait',)); self.play(g,'cry.wait')
                snapshot=g.snapshot(); carrier=self.first(g).id
                abilities=snapshot['state']['entities'][str(carrier)]['abilities']
                ability=next(a for a in abilities if a['kind']=='battlecry_repeat')
                if mode.startswith('kinds.'):
                    ability['battlecry_repeat']['kinds']=['minion'] if mode=='kinds.trim' else ['minion','weapon']
                elif mode=='origin': ability['origin']='granted'
                elif mode=='source': ability['source_id']=g.state.players[1].board[1]
                elif mode=='expiry': ability['expires_turn']=g.state.turn+1
                elif mode=='silence.policy': ability['remove_on_silence']=False
                else:
                    abilities.remove(ability)
                    snapshot['state']['entities'][str(g.state.players[1].board[1])]['abilities'].append(ability)
                # The current minion is still supported, and count remains two:
                # family/max checks alone cannot prove this surviving identity.
                self.assertEqual(snapshot['state']['battlecry_batches'][0]['plan']['repetitions'],2)
                self.reject(snapshot)
        # The public control effect moves the entire same carrier and preserves
        # its attachment identities. Its previously accepted plan stays valid.
        self.r=fixture_registry(); g=self.game(hand=('bc.transfer.wait',))
        carrier=self.first(g); identity=carrier.id; ability_ids=tuple(a.id for a in carrier.abilities)
        self.play(g,'bc.transfer.wait')
        self.assertEqual(g.state.entities[identity].controller,2)
        self.assertEqual(tuple(a.id for a in g.state.entities[identity].abilities),ability_ids)
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,2)
        for _ in range(2): self.check(g); self.choose(g)
        self.assertEqual(self.armor(g),2); self.check(g)

    def test_surviving_same_id_player_bc_source_keeps_full_origin_clock_scope_and_legal_use_decrement(self):
        for mode in ('kinds','source','creation','expiry','owner','use.increase'):
            with self.subTest(mode=mode):
                self.r=fixture_registry(); policy='script.bc.two.uses' if mode=='use.increase' else 'script.bc.persistent'
                g=self.game(hand=(policy,'cry.wait')); self.play(g,policy)
                g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g,'cry.wait')
                self.check(g)  # Includes the legitimate two-uses -> one acceptance consumption.
                snapshot=g.snapshot(); modifiers=snapshot['state']['players']['1']['battlecry_modifiers']
                modifier=modifiers[0]
                if mode=='kinds': modifier['spec']['kinds']=['minion']
                elif mode=='source':
                    modifier['source_id']=g.state.players[1].hero_id; modifier['source_card_id']='hero'
                elif mode=='creation': modifier['created_turn']=g.state.turn-1
                elif mode=='expiry': modifier['expires_turn']=g.state.turn+1
                elif mode=='owner':
                    modifiers.remove(modifier); snapshot['state']['players']['2']['battlecry_modifiers'].append(modifier)
                else:
                    self.assertEqual(modifier['uses_remaining'],1); modifier['uses_remaining']=2
                self.reject(snapshot)

    def test_battlecry_original_acceptance_marker_cannot_be_missing_duplicated_or_payload_trimmed(self):
        for mode in ('missing','duplicate','payload.trimmed'):
            with self.subTest(mode=mode):
                self.r=fixture_registry(); g=self.game(hand=('cry.wait',)); self.play(g,'cry.wait')
                snapshot=g.snapshot(); queue=snapshot['resolution_frame']['fields']['continuation']['tuple']
                closer=next(w for w in queue if w.get('type','').endswith('.FinishBattlecryAcceptance'))
                if mode=='missing': queue.remove(closer)
                elif mode=='duplicate': queue.append(deepcopy(closer))
                else: closer['fields']['payloads']['tuple']=[]
                self.reject(snapshot)

    def test_consumed_once_player_bc_max_is_retained_by_proof_without_mutating_other_families(self):
        g=self.game(hand=('script.bc.finite','cry.wait')); self.play(g,'script.bc.finite')
        self.play(g,'cry.wait')
        self.assertEqual(g.state.players[1].battlecry_modifiers,[])
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,3)
        for _ in range(3): self.check(g); self.choose(g)
        self.assertEqual(sum(e.kind=='battlecry_modifier_used' for e in g.events),1)
        self.assertEqual(self.armor(g),3); self.assertEqual(self.counts(g),(2,2,2,2)); self.check(g)

    def test_colossal_appendage_four_policies_contribute_after_real_entry_before_bc_acceptance(self):
        g=self.game(board=('rattle','end'),hand=('colossal.wait',)); self.play(g,'colossal.wait')
        self.assertEqual(g.state.battlecry_batches[0].plan.repetitions,2)
        self.assertEqual(self.counts(g),(2,2,2,2))
        self.check(g); self.choose(g); self.check(g); self.choose(g)
        self.assertEqual(self.armor(g),2); self.check(g)

    def test_dr_whole_acceptance_proof_cannot_be_duplicated_or_lose_typed_context(self):
        for mode in ('duplicate','missing.context','missing.batch'):
            with self.subTest(mode=mode):
                self.r=fixture_registry(); g=self.waiting_dr_proof('return'); snapshot=g.snapshot()
                queue=snapshot['resolution_frame']['fields']['continuation']['tuple']
                closer=next(w for w in queue if w.get('type','').endswith('.FinishDeathrattleBatch'))
                if mode=='duplicate': queue.append(deepcopy(closer))
                else: closer['fields'].pop(mode.split('.')[1])
                self.reject(snapshot)

    def test_dr_complete_acceptance_proof_keeps_removed_player_instance_and_original_max(self):
        g=self.game(board=('mixed','dr.player','end'),hand=('script.pe.install','script.pe.invoke'))
        self.play(g,'script.pe.install'); self.play(g,'script.pe.invoke')
        self.assertEqual(g.state.players[1].player_effects,[])
        self.assertEqual(g.state.deathrattle_batches[0].plan.repetitions,3)
        corrupt=self.shrink_dr_tail(g.snapshot())
        def drop_player(value):
            if isinstance(value,dict):
                if 'repetitions' in value and 'contributors' in value:
                    contributors=value['contributors']
                    if isinstance(contributors,dict): contributors=contributors.get('tuple',[])
                    contributors[:]=[s for s in contributors if 'instance' not in s.get('fields',s)]
                for child in value.values(): drop_player(child)
            elif isinstance(value,list):
                for child in value: drop_player(child)
        drop_player(corrupt); self.reject(corrupt)
        self.choose(g); self.assertEqual(self.armor(g),3); self.check(g)

    def test_last_turn_player_source_covers_nested_dr_batches_before_single_owner_expiry(self):
        g=self.game(board=('mixed','dr.proof.keep','end.pe'),hand=('script.pe.install',))
        self.play(g,'script.pe.install'); g.apply(EndTurn(1)); choices=0
        while g.state.pending_choice:
            self.assertEqual(g.state.players[1].player_effects[0].remaining_turns,1)
            self.check(g); self.choose(g); choices+=1
        self.assertEqual(choices,2); self.assertEqual(self.armor(g),6)
        self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[3,3])
        self.assertEqual(g.state.players[1].player_effects,[])
        self.assertEqual(sum(e.kind=='player_effect_expired' for e in g.events),1)
        self.assertEqual(sum(e.kind=='turn_ended' for e in g.events),1); self.check(g)

    def test_parent_end_and_nested_dr_terminal_keep_prior_completion_and_interrupt_all_unstarted_positions(self):
        g=self.game(board=('mixed.three','dr.fatal','end.fatal'),hand=()); g.apply(EndTurn(1))
        self.assertNotEqual(g.state.status,'playing')
        rows=g.state.deathrattle_history
        self.assertEqual([(r.completed,r.interrupted) for r in rows],[(True,False),(False,True),(False,True)])
        self.assertEqual([r.execution_order for r in rows],[1,2,None])
        self.assertTrue(all(r.interrupted and not r.completed for r in g.state.end_turn_history))
        self.assertEqual(len(g.state.end_turn_history),3)
        self.assertEqual(g.state.end_turn_batches[0].plans[0].repetitions,3)
        self.assertEqual(self.armor(g),1); self.check(g)

    def test_cross_family_action_failure_restores_rng_as_well_as_all_nested_roots(self):
        g=self.game(hand=('battlecry.fail.random',),enemy=('plain',)); before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'mixed random branch failed'):
            self.play(g,'battlecry.fail.random')
        self.assertEqual(g.snapshot(),before)

    def test_rehashed_cross_family_ability_field_substitution_is_rejected(self):
        g=self.game(); snapshot=g.snapshot(); carrier=self.first(g).id
        abilities=snapshot['state']['entities'][str(carrier)]['abilities']
        for index in range(4):
            corrupt=deepcopy(snapshot)
            target=corrupt['state']['entities'][str(carrier)]['abilities'][index]
            other=abilities[(index+1)%4]
            field=other['kind']
            target[field]=other[field]
            corrupt['state_hash']=canonical_hash({k:v for k,v in corrupt.items()
                if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError): Game.from_snapshot(corrupt,fixture_registry())

    def test_duplicate_attachment_id_between_families_cannot_merge_sources_on_restore(self):
        g=self.game(); snapshot=g.snapshot(); carrier=self.first(g).id
        abilities=snapshot['state']['entities'][str(carrier)]['abilities']
        abilities[1]['id']=abilities[0]['id']
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot,fixture_registry())

    def test_complete_mixed_acceptance_proofs_require_schema_100_and_reject_99_explicitly(self):
        g=self.game(); snapshot=g.snapshot(); self.assertEqual(snapshot['schema_version'],266)
        snapshot['schema_version']=99
        with self.assertRaisesRegex(SnapshotError,'1 through 265'):
            Game.from_snapshot(snapshot,fixture_registry())

        # Keep all original legacy-schema cases above; append the former current109.
        old_current = g.snapshot()
        old_current['schema_version'] = 109
        with self.assertRaisesRegex(SnapshotError, '1 through 265'):
            Game.from_snapshot(old_current, fixture_registry())
        # Exact int schema110 rejects bool/string/float encodings.
        for bad_schema in (True, False, '110', 110.0):
            wrong_type = g.snapshot()
            wrong_type['schema_version'] = bad_schema
            with self.subTest(schema_type=type(bad_schema).__name__), self.assertRaises(SnapshotError):
                Game.from_snapshot(wrong_type, fixture_registry())

    def test_mixed_fields_require_their_own_spec_type_and_minion_carrier(self):
        for field,value in (('battlecry_repeats',DeathrattleRepeatSpec()),
                ('deathrattle_repeats',HeroPowerRepeatSpec()),
                ('hero_power_repeats',EndTurnRepeatSpec()),
                ('end_turn_repeats',BattlecryRepeatSpec())):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('invalid','invalid',CardType.MINION,health=8,**{field:(value,)}))
        for kind in (CardType.SPELL,CardType.WEAPON,CardType.HERO_POWER):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('invalid','invalid',kind,**declarations()))


if __name__ == '__main__': unittest.main()
