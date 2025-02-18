echo start
#!/bin/zsh
hostUser=guy
server=192.168.1.45

echo ...
# Function to open a new tab and run a command
open_tab() {
  echo service: $1
  fullCommand="ssh $hostUser@$server && ~/$1/run_logs.sh"
  echo full=$fullCommand
  osascript -e "tell application \"Terminal\"
    activate
    do script \"ssh $host@$server\"
    do script \"~/$1/run_logs.sh\"
    #do script \"$fullCommand\"
  end tell"
}

# Start SSH agent and add key with passphrase
#eval $(ssh-agent -s)
#ssh-add ~/.ssh/id_rsa <<< "your_passphrase_here"

echo open tab
# Open first tab and run command
open_tab refPortalService

# Open second tab and run command
#open_tab "ssh user@server2 && your_command_here"

# Open third tab and run command
#open_tab "ssh user@server3 && your_command_here"

echo "All SSH sessions started!"

