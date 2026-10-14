"""Public synthetic lifecycle of magnetic bodies and ongoing abilities."""
from dataclasses import replace
import json,sys
from hs_sim.engine import (BodyReference, BodyRootTargetBinding, BodyTargetBinding,
    BodyTargetProfile, CardDefinition, CardType, Game, GrantBattlecry, GrantCombo,
    Keyword, PlayerSetup, Registry, Scenario, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, GrantTrigger, RandomDamage, RemoveEnchantment,
    RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.model import CardClass,CardMetadata

FRIEND=TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,),'friendly')
ENEMY=replace(FRIEND,mode=TargetMode.REQUIRED,relation='enemy')
HAND=TargetSpec(TargetMode.OPTIONAL,(Zone.HAND,),(CardType.MINION,),'friendly')

def registry(mode='normal'):
    r=Registry('magnetic-body-lifecycle-'+mode)
    r.register_body_target_profile(BodyTargetProfile('paid','paid_hand','manual','pre_payment'))
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=100))
    r.register_behavior('body',lambda c:[GainArmor(c.player_id,1)])
    r.register_behavior('host_body',lambda c:[GainArmor(c.player_id,10)])
    r.register_behavior('persistent',lambda c:[GainArmor(c.player_id,3)])
    r.register_behavior('trigger',lambda c:[GainArmor(c.player_id,2)] if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id=='marker' else [])
    r.register_behavior('ordinary',lambda c:[Damage(c.target_id,2,c.source_id)])
    mech=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
    r.register_card(CardDefinition('host','Host',CardType.MINION,attack=1,health=30,
        battlecry='host_body',combo='host_body',keywords=(Keyword.COMBO,),metadata=mech))
    r.register_card(CardDefinition('enemy','Enemy',CardType.MINION,attack=1,health=30))
    r.register_card(CardDefinition('fodder','Fodder',CardType.MINION,attack=1,health=10))
    r.register_card(CardDefinition('material','Material',CardType.MINION,cost=2,attack=1,health=20,
        battlecry='body',combo='body',on_play='ordinary',targeting=FRIEND,
        deathrattle='persistent',triggers=(TriggerSpec('card_played','trigger'),),
        keywords=(Keyword.MAGNETIC,Keyword.COMBO,Keyword.TAUNT),magnetic_tribes=('mech',),metadata=mech))
    for name,family,domain in (('hand_body','battlecry',HAND),('enemy_combo','combo',ENEMY),('none_combo','combo',None)):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=10,
            **{family:'body','targeting':domain,'keywords':(Keyword.COMBO,) if family=='combo' else ()}))
    for name,family in (('material','battlecry'),('material','combo'),('hand_body','battlecry'),('enemy_combo','combo'),('none_combo','combo')):
        r.register_body_target_binding(BodyTargetBinding(name,family,'paid',carrier_card_ids=('material',)))
    r.register_body_root_target_binding(BodyRootTargetBinding('material','paid','explicit_root',ENEMY))
    def setup(c):
        e=next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='material')
        ref=BodyReference.capture(e)
        return [GrantBattlecry(ref,'hand_body',c.source_id),GrantCombo(ref,'enemy_combo',c.source_id),
            GrantCombo(ref,'none_combo',c.source_id)]
    def spell(name,behavior,targeted=False):
        r.register_behavior(name,behavior);r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=targeted))
    spell('setup',setup)
    spell('marker',lambda c:[])
    spell('kill',lambda c:[Destroy(c.target_id)],True)
    spell('copy',lambda c:[CopyMinion(c.target_id,1)],True)
    spell('base_copy',lambda c:[CopyMinion(c.target_id,1,mode='base')],True)
    spell('silence',lambda c:[Silence(c.target_id)],True)
    spell('bounce',lambda c:[ReturnToHand(c.target_id)],True)
    spell('transform',lambda c:[Transform(c.target_id,'fodder')],True)
    spell('control',lambda c:[ChangeControl(c.target_id,2)],True)
    spell('remove',lambda c:[RemoveEnchantment(c.target_id,next(a.id for a in c.state.entities[c.target_id].enchantments if a.magnetic_id is not None))],True)
    spell('temporary',lambda c:[GrantTrigger(c.target_id,'card_played','trigger',c.source_id,expires_turn=c.state.turn)],True)
    if mode in ('departure','wait','fail'):
        def react(c):
            if c.event.source_id is None or c.state.entities[c.event.source_id].card_id!='material':return []
            if mode=='departure':return [Destroy(c.state.players[1].board[0])]
            if mode=='wait':return [RequestChoice(c.player_id,(ChoiceOption('go','Continue'),),c.source_id)]
            return [RandomDamage((c.state.players[2].hero_id,),1,c.source_id),Summon(c.player_id,'unsupported.magnetic.lifecycle')]
        r.register_behavior('react',react)
        r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=10,
            triggers=(TriggerSpec('card_committed' if mode=='departure' else 'magnetized','react'),)))
    return r

def scenario(mode='normal',*,multiple=False,tools=('kill',)):
    return Scenario((PlayerSetup('hero',hand=('setup','material','fodder','marker',*tools,*(('setup','material') if multiple else ())),
        board=('host',)+(('watcher',) if mode in ('departure','wait','fail') else ()),mana=10,max_mana=10),
        PlayerSetup('hero',hand=('marker','kill'),board=('enemy',),mana=10,max_mana=10)),seed=43)

def ref(game,name,viewer=1):
    return next(c['ref'] for c in game.for_player(viewer).observe()['observation']['players'][viewer-1]['hand'] if c.get('card_id')==name)

def paid_command(game,position=0):
    options=game.for_player(1).independent_targets(ref(game,'material'),position=position)
    assert options['error'] is None and options['choices']
    choice=options['choices'][0]
    return {'revision':options['revision'],'action':{'type':'play_card','card':choice['card'],
        'position':position,'target':choice['root_targets'][0],'body_targets':[{'body':b['body'],
            'target':next((t for t in b['targets'] if t is not None),None)} for b in choice['bodies']]}}

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'normal'
    game=Game.from_scenario(scenario(mode),registry(mode));initial=game.snapshot();commands=[];positions=[]
    def submit(action):
        port=game.for_player(1);command={'revision':port.observe()['revision'],'action':action}
        commands.append(command);response=port.submit(command);assert response['accepted'],response
    submit({'type':'play_card','card':ref(game,'setup')})
    commands.append(paid_command(game));assert game.for_player(1).submit(commands[-1])['accepted']
    def capture():positions.append({'after_commands':len(commands),'snapshot':game.snapshot(),
        'observations':[game.for_player(i).observe() for i in (1,2)]})
    capture()
    while game.state.pending_choice is not None:
        legal=game.for_player(1).legal_actions();submit(legal['actions'][0]);capture()
    if mode!='departure':submit({'type':'play_card','card':ref(game,'marker')});capture()
    print(json.dumps({'mode':mode,'initial':initial,'commands':commands,'positions':positions,'final':game.snapshot()},ensure_ascii=False))

if __name__=='__main__':main()
