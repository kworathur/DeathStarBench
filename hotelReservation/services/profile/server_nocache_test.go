//go:build no_memcache

package profile

import (
	"context"
	"errors"
	"reflect"
	"testing"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/profile/proto"
	"go.mongodb.org/mongo-driver/mongo"
	"pgregory.net/rapid"
)

func TestNoMemcacheGetProfilesProperty(t *testing.T) {
	oldGetProfileFromMongo := getProfileFromMongo
	t.Cleanup(func() {
		getProfileFromMongo = oldGetProfileFromMongo
	})

	var calls []string
	getProfileFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (*pb.Hotel, error) {
		calls = append(calls, hotelId)
		return &pb.Hotel{Id: hotelId}, nil
	}

	rapid.Check(t, func(t *rapid.T) {
		hotelIds := rapid.SliceOfN(rapid.StringMatching(`[a-z0-9]{1,8}`), 1, 20).Draw(t, "hotelIds")
		calls = calls[:0]

		res, err := (&Server{}).GetProfiles(context.Background(), &pb.Request{HotelIds: hotelIds})
		if err != nil {
			t.Fatalf("GetProfiles returned error: %v", err)
		}
		if !reflect.DeepEqual(calls, hotelIds) {
			t.Fatalf("Mongo calls = %v, want %v", calls, hotelIds)
		}
		if len(res.Hotels) != len(hotelIds) {
			t.Fatalf("len(res.Hotels) = %d, want %d", len(res.Hotels), len(hotelIds))
		}
		for i, hotel := range res.Hotels {
			if hotel.GetId() != hotelIds[i] {
				t.Fatalf("res.Hotels[%d].Id = %q, want %q", i, hotel.GetId(), hotelIds[i])
			}
		}
	})
}

func TestNoMemcacheGetProfilesReturnsMongoError(t *testing.T) {
	oldGetProfileFromMongo := getProfileFromMongo
	t.Cleanup(func() {
		getProfileFromMongo = oldGetProfileFromMongo
	})

	wantErr := errors.New("mongo failed")
	getProfileFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (*pb.Hotel, error) {
		return nil, wantErr
	}

	_, err := (&Server{}).GetProfiles(context.Background(), &pb.Request{HotelIds: []string{"1"}})
	if !errors.Is(err, wantErr) {
		t.Fatalf("GetProfiles error = %v, want %v", err, wantErr)
	}
}
