"""Public synthetic paid Rewind forms with explicit per-body retry authority."""
from dataclasses import replace
import json,sys
from hs_sim.engine import (BodyReference,BodyRootTargetBinding,BodyTargetBinding,
    BodyTargetProfile,CardDefinition,CardType,Game,GrantBattlecry,GrantCombo,
    Keyword,PlayerSetup,Registry,RewindSpec,Scenario,TargetMode,TargetSpec,Zone)
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,GainArmor,RandomDamage,RequestChoice,Summon)

FRIEND=TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,),'friendly')
ENEMY=replace(FRIEND,mode=TargetMode.REQUIRED,relation='enemy')
FACES=('unit','face1','face2')

def registry(mode='normal',*,missing_face=False,restricted=False):
    r=Registry('paid-body-retry-'+mode+str(missing_face)+str(restricted))
    r.register_body_target_profile(BodyTargetProfile('paid','paid_hand','manual','pre_payment',retry_targets='reuse_original_selection'))
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=100))
    for name in ('friend','enemy','hidden'):
        r.register_card(CardDefinition(name,name,CardType.MINION,attack=1,health=20))
    def root(c):
        effects=[Damage(c.target_id,2,c.source_id),RandomDamage(tuple(c.state.players[2].board),1,c.source_id)]
        if mode=='fail' and c.rewind_attempt>0:effects.append(Summon(c.player_id,'unsupported.retry'))
        if mode=='wait':return [RequestChoice(c.player_id,(ChoiceOption('go','Continue',tuple(effects)),),c.source_id)]
        return effects
    r.register_behavior('root',root)
    def body(c):
        effects=[GainArmor(c.player_id,1),*( [Buff(c.target_id,attack=1,source_id=c.source_id)] if c.target_id is not None else [])]
        if mode=='body_wait':return [RequestChoice(c.player_id,(ChoiceOption('go','Continue',tuple(effects)),),c.source_id)]
        return effects
    r.register_behavior('body',body)
    for index,name in enumerate(FACES):
        specs=dict(cost=2,attack=1,health=20,on_play='root',targeting=FRIEND)
        if mode!='empty':specs.update(battlecry='body',combo='body',keywords=(Keyword.COMBO,))
        if index<2:
            specs.update(rewind=RewindSpec(2-index,FACES[index+1]),keywords=(*specs.get('keywords',()),Keyword.REWIND))
        r.register_card(CardDefinition(name,name,CardType.MINION,**specs))
        if not(missing_face and index==1):r.register_body_root_target_binding(BodyRootTargetBinding(name,'paid','explicit_root',ENEMY))
    if mode!='empty':
        for family in ('battlecry','combo'):
            r.register_body_target_binding(BodyTargetBinding('unit',family,'paid',('printed',),carrier_card_ids=FACES))
    for name,threshold in (('low',5),('high',9)):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=20,battlecry='body',combo='body',targeting=ENEMY,
            target_condition='manathirst',manathirst=threshold,keywords=(Keyword.COMBO,Keyword.MANATHIRST)))
        for family in ('battlecry','combo'):
            r.register_body_target_binding(BodyTargetBinding(name,family,'paid',('granted',),carrier_card_ids=('unit',) if restricted else FACES))
    def setup(c):
        e=next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='unit')
        return [effect(BodyReference.capture(e),name,c.source_id) for name in ('low','high') for effect in (GrantBattlecry,GrantCombo)]
    r.register_behavior('setup',setup);r.register_card(CardDefinition('setup','Setup',CardType.SPELL,on_play='setup'))
    return r

def scenario(*,grants=True,crystals=10):
    return Scenario((PlayerSetup('hero',hand=(*(('setup',) if grants else ()),'unit'),board=('friend','friend'),mana=crystals,max_mana=crystals),
        PlayerSetup('hero',board=('enemy','enemy'),hand=('hidden',),mana=10,max_mana=10)),seed=43)

def card_ref(game,name):
    return next(c['ref'] for c in game.for_player(1).observe()['observation']['players'][0]['hand'] if c.get('card_id')==name)

def command(game):
    port=game.for_player(1);q=port.independent_targets(card_ref(game,'unit'),position=0);assert q['error'] is None and len(q['choices'])==1,q
    route=q['choices'][0];action={'type':'play_card','card':route['card'],'target':route['root_targets'][0],
        'position':0,'body_targets':[{'body':b['body'],'target':b['targets'][0]} for b in route['bodies']]}
    if not route['bodies']:action['body_route']=route['body_route']
    return {'revision':q['revision'],'action':action}

def choose_command(game,option='retry'):
    port=game.for_player(1);q=port.legal_actions();assert q['error'] is None,q
    observed=port.observe()['observation']['pending_choice']
    label='回溯并重试' if option=='retry' else '保留当前结果' if option=='keep' else 'Continue'
    handle=next(o['ref'] for o in observed['options'] if o['label']==label)
    return {'revision':q['revision'],'action':next(a for a in q['actions'] if a.get('options')==[handle])}

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'normal'
    g=Game.from_scenario(scenario(grants=mode!='empty'),registry(mode));initial=g.snapshot();commands=[];positions=[]
    def submit(command):
        response=g.for_player(1).submit(command);assert response['accepted'],response
        commands.append(command);positions.append({'after_commands':len(commands),'snapshot':g.snapshot(),
            'observations':[g.for_player(p).observe() for p in (1,2)]})
    if mode!='empty':submit({'revision':g.for_player(1).observe()['revision'],'action':{'type':'play_card','card':card_ref(g,'setup')}})
    submit(command(g))
    while g.state.pending_choice:
        submit(choose_command(g,'retry' if g.state.pending_choice.purpose.value=='rewind' else 'go'))
    print(json.dumps({'mode':mode,'initial':initial,'commands':commands,'positions':positions,'final':g.snapshot(),
        'observations':[g.for_player(p).observe() for p in (1,2)]},ensure_ascii=False))
if __name__=='__main__':main()
