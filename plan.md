# Chore Manager Plan and Vision

## Problem

I have a family of 4, myself, my partner, and two children. We have many things we need to regularly do in the household and sometimes it is a struggle to get everyone to do their bit. For the children we often reward them with screen time, and the goal should be that if their chores are not done, then can have screens.

Some of the types of chores might be:
- load the dishwasher (eg. clear the table after dinner)
- empty the dishwasher
- piano practice
- clarinet practice
- empty kitchen storage box
- tidy your items in the common living space
- tidy your room
- tidy the TV room

## Solution

My thoughts are that it would be good to have an app which could track these tasks, and who as done them. I think it should be web/html page which would be primarly rendered on an ipad or iphone (though I might view it on a computer browser). I want to be able to track tasks and rewards and who has done them. I want to game-ify this so that the kids find it fun and it's not a bore.

Some tasks will be repeated on a schedule. For instance, some will by daily, some will be weekly (on a certain day), some will be adhoc. I'm not sure about other frequencies like monthly or fortnightly, but we should probably consider and provide an option for this - just use the what most web calendars uses as options I guess.

I'm also thinking of a rewards tally too. Every chore done accumulates chore points (maybe a better name is in order?). We 

### Implementation

- We should start off simple and increase in complexity as we go. Start of with an MVP and expand!
- The website should be written in python - I don't care about the framework, potentially flask or something simple. I'm willing to take advice on this.
- I'm wondering how we store data. Initially I was thinking of using a yaml file for configuration - and I'm mostly in favour of this, potentially holding things like the list of people, and their repeated tasks. But may something like SQLite is more appropriate. If we are using python, maybe it's possible to use an ORM (object Relational Mapper) - you choose the best one I don't mind). This will mean we can move to any other backend later on. But SQLite should be pretty good for now.
  - perhaps yaml for basic configuration of the app
  - database (via ORM) for tasks and rewards
- We need functions written to be able to be unit tested - pytest?
- We want eventually build the application into a docker container
- We want to control the build process via a makefile - see Makefile.
- we don't need to worry about authentication right now - this is just a home family tool running locally.

### Interface

The view should be the tasks of the day, split up in a table. Each column could be a person, and the rows down the column the tasks to be done.
Something like
| Today's date/time | | CHORE MANAGER | |
| Person 1 | Person 2 | Person 3 | Person 4 |
| Piano Practice | clarinet practice | make school lunches | do budget |
| clear the table after dinner | pack up lego | empty the dishwasher | fold laundry |
| empty kitchen storage box | empty kitchen storage box | vacuum kitchen | put on new table cloth |
- Clicking on the chore (or touching on a ipad/iphone) should toggle it to be done or not, this could change it from red (not done) to green (done). Maybe some kind of confetti animation too - that would be fun.
- Maybe some way to show chore points and a way to cash them into things like pocket money or screen time.

# Future features
- DONE on the individual's page, we should show a counter of their chores done, and their reward points. A graph might be nice. Also some stats on their rate of completion. 
- DONE When all tasks are completed for a day I want to implement a tsparticles animation to show really big fireworks! (the confetti is just for completing a single task)
- DONE ability to have an image for each person
- SORT OF DONE admin interface to add/remove/modify tasks, add/remove/modify people, add/remove/modify chore points etc.

